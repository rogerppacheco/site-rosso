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
        if not self.webhook_url:
            logger.warning(
                "N8N_OUTBOUND_WEBHOOK_URL não configurada — outbound texto/mídia URL falhará"
            )

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

    def _dispatch_n8n(self, payload: Dict[str, Any], timeout: int = 15) -> Tuple[bool, Any]:
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
                return True, body
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

    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        phone = formatar_telefone_br(telefone)
        payload = {
            "phone_number": phone,
            "message_body": mensagem or "",
            "source": "site-record",
        }
        ok, resp = self._dispatch_n8n(payload, timeout=10)
        if ok:
            return True, resp if isinstance(resp, dict) else {"raw": resp}
        return False, resp

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
            "source": "site-record",
        }
        ok, _ = self._dispatch_n8n(payload, timeout=30)
        return ok

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
