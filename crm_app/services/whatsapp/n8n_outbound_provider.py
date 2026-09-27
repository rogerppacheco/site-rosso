"""Provider híbrido: outbound via n8n, operações diretas na Evolution quando necessário."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.evolution_provider import EvolutionProvider
from crm_app.services.whatsapp.phone_utils import formatar_telefone_br

logger = logging.getLogger(__name__)


class N8nOutboundProvider(WhatsAppProvider):
    """
    Envios de texto e mídia por URL passam pelo n8n (como sysr-vendas).
    Base64, botões, grupos e verificação de número usam Evolution direto.
    """

    def __init__(self) -> None:
        self.webhook_url = self._resolve_webhook_url()
        self._evolution = EvolutionProvider()
        self.fallback_direto = bool(
            getattr(settings, "N8N_OUTBOUND_DIRECT_FALLBACK", True)
        )
        if not self.webhook_url:
            logger.warning(
                "N8N_OUTBOUND_WEBHOOK_URL não configurada — outbound texto/mídia URL falhará"
            )

    def is_configured(self) -> bool:
        # Validação de número usa Evolution direto; n8n só afeta envios.
        return self._evolution.is_configured()

    @staticmethod
    def _resolve_webhook_url() -> str:
        for key in (
            "N8N_OUTBOUND_WEBHOOK_URL",
            "N8N_WEBHOOK_URL",
            "OUTBOUND_WEBHOOK_URL",
        ):
            val = getattr(settings, key, None) or os.environ.get(key, "")
            if val and str(val).strip():
                return str(val).strip()
        return ""

    def _resposta_confirma_entrega(
        self,
        resposta: Any,
        profundidade: int = 0,
    ) -> bool:
        if profundidade > 3:
            return False
        if isinstance(resposta, dict):
            if self.resposta_indica_sucesso(resposta):
                return True
            return any(
                self._resposta_confirma_entrega(
                    resposta.get(chave),
                    profundidade + 1,
                )
                for chave in ("body", "data", "response", "json")
                if chave in resposta
            )
        if isinstance(resposta, list):
            return any(
                self._resposta_confirma_entrega(item, profundidade + 1)
                for item in resposta
            )
        return False

    def _dispatch_n8n(
        self,
        payload: Dict[str, Any],
        timeout: int = 15,
    ) -> Tuple[bool, Any]:
        if not self.webhook_url:
            return False, "N8N_OUTBOUND_WEBHOOK_URL não configurada"
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            if resp.status_code in (200, 201, 202, 204):
                try:
                    body = resp.json() if resp.content else {}
                except ValueError:
                    body = {"status": resp.status_code}
                if self._resposta_confirma_entrega(body):
                    return True, body
                logger.error(
                    "[n8n outbound] HTTP %s sem confirmação de entrega: %s",
                    resp.status_code,
                    str(body)[:500],
                )
                return False, {
                    "error": "n8n não confirmou a entrega na Evolution",
                    "response": body,
                }
            logger.error(
                "[n8n outbound] HTTP %s: %s",
                resp.status_code,
                resp.text[:500],
            )
            return False, resp.text[:500]
        except requests.exceptions.RequestException as exc:
            logger.error("[n8n outbound] Request failed: %s", exc)
            return False, str(exc)

    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        return self._evolution.verificar_numero_existe(telefone)

    def _fallback_texto(
        self,
        telefone: str,
        mensagem: str,
        erro_n8n: Any,
    ) -> Tuple[bool, Any]:
        if not self.fallback_direto:
            return False, erro_n8n
        logger.warning(
            "[n8n outbound] Acionando fallback direto Evolution para texto: %s",
            str(erro_n8n)[:300],
        )
        ok, resposta = self._evolution.enviar_mensagem_texto_raw(
            telefone,
            mensagem,
        )
        if ok:
            return True, {
                "fallback": "evolution-direto",
                "n8n_error": erro_n8n,
                "response": resposta,
            }
        logger.error(
            "[n8n outbound] Fallback direto Evolution falhou: %s",
            str(resposta)[:500],
        )
        return False, {
            "n8n_error": erro_n8n,
            "fallback_error": resposta,
        }

    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        phone = formatar_telefone_br(telefone)
        payload = {
            "phone_number": phone,
            "message_body": mensagem or "",
            "source": "nova-velox",
        }
        ok, resp = self._dispatch_n8n(payload, timeout=10)
        if ok:
            return True, resp if isinstance(resp, dict) else {"raw": resp}
        return self._fallback_texto(telefone, mensagem, resp)

    def enviar_mensagem_com_botoes_reply(
        self,
        telefone: str,
        mensagem: str,
        button_actions: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        return self._evolution.enviar_mensagem_com_botoes_reply(
            telefone, mensagem, button_actions, title=title, footer=footer
        )

    def enviar_imagem_b64(
        self, telefone: str, img_b64: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        return self._evolution.enviar_imagem_b64(telefone, img_b64, caption=caption)

    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        phone = formatar_telefone_br(telefone)
        payload = {
            "phone_number": phone,
            "message_body": caption or "",
            "media_type": "document",
            "media_url": pdf_url,
            "media_mimetype": "application/pdf",
            "media_file_name": nome_arquivo,
            "source": "nova-velox",
        }
        ok, resposta = self._dispatch_n8n(payload, timeout=30)
        if ok:
            return True
        if not self.fallback_direto:
            return False
        logger.warning(
            "[n8n outbound] Acionando fallback direto Evolution para documento: %s",
            str(resposta)[:300],
        )
        return self._evolution.enviar_pdf_url(
            telefone,
            pdf_url,
            nome_arquivo,
            caption=caption,
        )

    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        return self._evolution.enviar_pdf_b64(
            telefone, base64_data, nome_arquivo, caption=caption
        )

    def listar_grupos(self) -> List[Dict[str, str]]:
        return self._evolution.listar_grupos()
