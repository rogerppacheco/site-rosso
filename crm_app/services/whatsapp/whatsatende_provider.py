"""Provider WhatsAtende (SouChat/Whaticket) — API documentada em /messages-api."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.phone_utils import formatar_telefone_br

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.app14.whatsatende.com.br"


class WhatsAtendeProvider(WhatsAppProvider):
    """
    Outbound via Bearer token da conexão (Conexões → token).

    role=interno → Número A (bot/equipe); role=cliente → Número B (oficial).
    Endpoints: send, linkImage, linkPDF, base64, checkNumber.
    Botões/lista/grupos: ainda sem doc pública — retornam não suportado.
    """

    def __init__(self, role: str = "interno") -> None:
        self.base_url = (
            getattr(settings, "WHATSATENDE_API_URL", None)
            or os.environ.get("WHATSATENDE_API_URL")
            or DEFAULT_API_URL
        ).rstrip("/")
        self.role = (role or "interno").strip().lower()
        if self.role == "cliente":
            # Nunca cair no Número A: envio a cliente deve falhar se B não estiver pronto.
            self.token = (
                getattr(settings, "WHATSATENDE_TOKEN_B", None)
                or os.environ.get("WHATSATENDE_TOKEN_B")
                or ""
            ).strip()
            self.whatsapp_id = str(
                getattr(settings, "WHATSATENDE_WHATSAPP_ID_B", None)
                or os.environ.get("WHATSATENDE_WHATSAPP_ID_B")
                or ""
            ).strip()
            if not self.token:
                logger.error(
                    "[WhatsAtende] WHATSATENDE_TOKEN_B ausente — "
                    "role=cliente abortará envios (sem fallback para A)."
                )
        else:
            self.token = (
                getattr(settings, "WHATSATENDE_TOKEN", None)
                or os.environ.get("WHATSATENDE_TOKEN")
                or ""
            ).strip()
            self.whatsapp_id = str(
                getattr(settings, "WHATSATENDE_WHATSAPP_ID", None)
                or os.environ.get("WHATSATENDE_WHATSAPP_ID")
                or ""
            ).strip()
        if not self.token:
            logger.error(
                "WhatsAtende CRITICO: token não configurado "
                "(role=%s; painel Conexões).",
                self.role,
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _destino(self, telefone: str) -> str:
        return formatar_telefone_br(telefone)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Any:
        url = f"{self.base_url}{path}"
        logger.debug(
            "[WhatsAtende] %s %s role=%s id=%s",
            method,
            url,
            getattr(self, "role", "?"),
            self.whatsapp_id or "-",
        )
        if not self.token:
            logger.error("[WhatsAtende] Sem token — abortando %s %s", method, path)
            return None
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
            if resp.status_code not in (200, 201):
                logger.error(
                    "[WhatsAtende] HTTP %s %s: %s",
                    resp.status_code,
                    path,
                    resp.text[:500],
                )
                try:
                    return resp.json()
                except ValueError:
                    return {"error": resp.text, "statusCode": resp.status_code}
            try:
                return resp.json()
            except ValueError:
                return {"raw": resp.text, "statusCode": resp.status_code}
        except requests.exceptions.RequestException as exc:
            logger.error("[WhatsAtende] Request failed %s: %s", path, exc)
            return None

    def _message_id(self, resp: Any) -> Optional[str]:
        if not isinstance(resp, dict):
            return None
        for key in ("messageId", "id", "zaapId", "key"):
            val = resp.get(key)
            if isinstance(val, dict) and val.get("id"):
                return str(val["id"])
            if val and not isinstance(val, (dict, list)):
                return str(val)
        for nest in ("data", "message", "ticket"):
            nested = resp.get(nest)
            if isinstance(nested, dict):
                mid = self._message_id(nested)
                if mid:
                    return mid
        return None

    def resposta_indica_sucesso(self, resp: Any) -> bool:
        if not resp or not isinstance(resp, dict):
            return False
        if resp.get("error") or resp.get("statusCode", 200) not in (200, 201):
            return False
        if self._message_id(resp):
            return True
        # Doc / testes: "messages scheduled" e variações
        status = str(resp.get("status") or resp.get("message") or "").lower()
        if any(
            token in status
            for token in ("scheduled", "success", "ok", "enviad", "pending", "created")
        ):
            return True
        if resp.get("success") is True:
            return True
        # Resposta sem erro explícito e com corpo útil
        if "raw" in resp and resp.get("statusCode") in (200, 201, None):
            return True
        return False

    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        if not self.token:
            return True
        numero = self._destino(telefone)
        data = self._request(
            "POST", "/api/messages/checkNumber", {"number": numero}
        )
        if not isinstance(data, dict):
            return None
        if data.get("error") and data.get("statusCode", 200) not in (200, 201):
            return None
        # Resposta oficial app14: existsInWhatsapp
        if "existsInWhatsapp" in data:
            return bool(data["existsInWhatsapp"])
        for key in ("exists", "numberExists", "isWhatsapp", "whatsapp"):
            if key in data:
                return bool(data[key])
        nested = data.get("data") or data.get("result") or data.get("contact")
        if isinstance(nested, dict):
            if "existsInWhatsapp" in nested:
                return bool(nested["existsInWhatsapp"])
            for key in ("exists", "numberExists", "isWhatsapp", "whatsapp"):
                if key in nested:
                    return bool(nested[key])
        if data.get("status") == "success" and data.get("number"):
            return True
        logger.warning(
            "[WhatsAtende] checkNumber resposta ambígua para %s: %s",
            numero,
            str(data)[:300],
        )
        return None

    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        numero = self._destino(telefone)
        payload = {
            "number": numero,
            "body": mensagem or "",
            "closeTicket": False,
            "msdelay": 1000,
        }
        resp = self._request("POST", "/api/messages/send", payload)
        if self.resposta_indica_sucesso(resp):
            mid = self._message_id(resp)
            logger.info(
                "[WhatsAtende] Texto enviado role=%s id=%s para %s messageId=%s",
                getattr(self, "role", "?"),
                self.whatsapp_id or "-",
                numero,
                mid,
            )
            if isinstance(resp, dict) and mid and "messageId" not in resp:
                resp = {**resp, "messageId": mid}
            return True, resp
        erro = resp
        if isinstance(resp, dict):
            erro = resp.get("message") or resp.get("error") or resp
        logger.error("[WhatsAtende] Falha texto para %s: %s", numero, erro)
        return False, erro if erro is not None else "Erro ao enviar"

    def enviar_template(
        self,
        telefone: str,
        template_name: str,
        language_code: str = "pt_BR",
        template_params: Optional[Any] = None,
        body_params: Optional[List[str]] = None,
    ) -> Tuple[bool, Any]:
        """
        Envio de template Meta (Número B / Cloud API).
        Fora da janela de 24h é obrigatório.

        body_params: lista ordenada das variáveis do BODY ({{1}}, {{2}}, …).
        """
        numero = self._destino(telefone)
        lang = language_code or "pt_BR"
        params_list: List[str] = []
        if body_params:
            params_list = [str(p) if p is not None else "-" for p in body_params]
        elif isinstance(template_params, list):
            params_list = [str(p) if p is not None else "-" for p in template_params]
        elif isinstance(template_params, dict):
            if isinstance(template_params.get("body"), list):
                params_list = [str(p) for p in template_params["body"]]
            else:
                keys = sorted(
                    (k for k in template_params.keys() if str(k).isdigit()),
                    key=lambda x: int(str(x)),
                )
                if keys:
                    params_list = [str(template_params[k]) for k in keys]

        template_obj: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": lang},
        }
        if params_list:
            template_obj["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": p if str(p).strip() else "-"}
                        for p in params_list
                    ],
                }
            ]

        payload: Dict[str, Any] = {
            "number": numero,
            "template": template_obj,
        }
        if self.whatsapp_id:
            try:
                payload["whatsappId"] = int(self.whatsapp_id)
            except (TypeError, ValueError):
                payload["whatsappId"] = self.whatsapp_id
        if params_list:
            payload["templateParams"] = params_list

        resp = self._request("POST", "/api/messages/send", payload)
        if self.resposta_indica_sucesso(resp):
            mid = self._message_id(resp)
            if isinstance(resp, dict) and mid and "messageId" not in resp:
                resp = {**resp, "messageId": mid}
            logger.info(
                "[WhatsAtende] Template %s enviado para %s (vars=%s)",
                template_name,
                numero,
                len(params_list),
            )
            return True, resp
        logger.error(
            "[WhatsAtende] Falha template %s para %s: %s",
            template_name,
            numero,
            resp,
        )
        return False, resp

    def listar_templates(self) -> Any:
        return self._request("GET", "/api/messages/templates")

    def enviar_imagem_url(
        self, telefone: str, url: str, caption: str = ""
    ) -> Tuple[bool, Any]:
        numero = self._destino(telefone)
        payload = {
            "number": numero,
            "msdelay": 1000,
            "url": url,
            "caption": caption or "",
        }
        resp = self._request("POST", "/api/messages/send/linkImage", payload, timeout=60)
        return self.resposta_indica_sucesso(resp), resp

    def enviar_mensagem_com_botoes_reply(
        self,
        telefone: str,
        mensagem: str,
        button_actions: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        # Aguardando confirmação do suporte (endpoint não documentado).
        logger.info(
            "[WhatsAtende] Botões reply ainda não suportados na API documentada "
            "(telefone=%s, botoes=%s)",
            telefone,
            len(button_actions or []),
        )
        return False, None

    def enviar_lista_opcoes(
        self,
        telefone: str,
        mensagem: str,
        opcoes: List[Dict[str, str]],
        titulo_lista: str = "Opções",
        botao_label: str = "Ver opções",
    ) -> Tuple[bool, Any]:
        logger.info(
            "[WhatsAtende] Lista de opções ainda não suportada na API documentada "
            "(telefone=%s, opcoes=%s)",
            telefone,
            len(opcoes or []),
        )
        return False, None

    def enviar_imagem_b64(
        self, telefone: str, img_b64: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        numero = self._destino(telefone)
        data = img_b64 or ""
        if "base64," not in data:
            data = "data:image/png;base64," + data
        payload = {
            "number": numero,
            "base64Data": data,
            "fileName": "image.png",
            "caption": caption or "",
            "msdelay": 1000,
        }
        resp = self._request("POST", "/api/messages/send/base64", payload, timeout=60)
        if self.resposta_indica_sucesso(resp) and isinstance(resp, dict):
            mid = self._message_id(resp)
            if mid and "messageId" not in resp:
                resp = {**resp, "messageId": mid}
            return resp
        return None

    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        numero = self._destino(telefone)
        payload: Dict[str, Any] = {
            "number": numero,
            "fileUrl": pdf_url,
            "caption": caption or nome_arquivo,
            "msdelay": 1000,
        }
        resp = self._request("POST", "/api/messages/send/linkPDF", payload, timeout=60)
        return self.resposta_indica_sucesso(resp)

    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        numero = self._destino(telefone)
        data = base64_data or ""
        if data.startswith("data:") and "base64," in data:
            data = data.split("base64,", 1)[1]
        data = data.replace("\r", "").replace("\n", "")
        payload: Dict[str, Any] = {
            "number": numero,
            "base64Data": f"data:application/pdf;base64,{data}",
            "fileName": nome_arquivo or "extrato.pdf",
            "caption": caption or "",
            "msdelay": 1000,
        }
        resp = self._request("POST", "/api/messages/send/base64", payload, timeout=90)
        return self.resposta_indica_sucesso(resp)

    def listar_grupos(self) -> List[Dict[str, str]]:
        logger.info(
            "[WhatsAtende] listar_grupos ainda não documentado na API pública"
        )
        return []
