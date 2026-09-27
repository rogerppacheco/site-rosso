"""Provider Cloud API Meta (graph.facebook.com) — envio direto sem BSP."""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.phone_utils import formatar_telefone_br

logger = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com"


def _setting(name: str, default: str = "") -> str:
    val = getattr(settings, name, None)
    if val is None:
        val = os.environ.get(name, default)
    return str(val or default).strip()


class MetaCloudProvider(WhatsAppProvider):
    """
    POST /{PHONE_NUMBER_ID}/messages na Graph API.

    Destinado a purpose=cliente (templates / janela 24h).
    Grupos não são suportados neste provedor.
    """

    def __init__(self) -> None:
        self.token = _setting("META_CLOUD_ACCESS_TOKEN")
        self.phone_number_id = _setting("META_CLOUD_PHONE_NUMBER_ID")
        self.waba_id = _setting("META_CLOUD_WABA_ID")
        self.version = _setting("META_CLOUD_API_VERSION", "v21.0") or "v21.0"
        if not self.token or not self.phone_number_id:
            logger.error(
                "[MetaCloud] META_CLOUD_ACCESS_TOKEN ou "
                "META_CLOUD_PHONE_NUMBER_ID ausente — envios abortarão."
            )

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.version}/{str(path).lstrip('/')}"

    def _headers_json(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _destino(self, telefone: str) -> str:
        return formatar_telefone_br(telefone)

    def _post_messages(self, payload: Dict[str, Any]) -> Any:
        if not self.token or not self.phone_number_id:
            return {"error": {"message": "credenciais Meta ausentes"}}
        try:
            resp = requests.post(
                self._url(f"{self.phone_number_id}/messages"),
                headers=self._headers_json(),
                json=payload,
                timeout=30,
            )
            try:
                data = resp.json()
            except ValueError:
                data = {"error": {"message": resp.text[:500]}, "statusCode": resp.status_code}
            if resp.status_code not in (200, 201):
                logger.error(
                    "[MetaCloud] HTTP %s /messages: %s",
                    resp.status_code,
                    str(data)[:500],
                )
            return data
        except requests.RequestException as exc:
            logger.error("[MetaCloud] request failed: %s", exc)
            return {"error": {"message": str(exc)}}

    def _message_id(self, resp: Any) -> Optional[str]:
        if not isinstance(resp, dict):
            return None
        msgs = resp.get("messages")
        if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
            mid = msgs[0].get("id")
            if mid:
                return str(mid)
        return None

    def resposta_indica_sucesso(self, resp: Any) -> bool:
        if not resp or not isinstance(resp, dict):
            return False
        if resp.get("error"):
            return False
        return bool(self._message_id(resp))

    def _ok_resp(self, resp: Any) -> Tuple[bool, Any]:
        if self.resposta_indica_sucesso(resp):
            mid = self._message_id(resp)
            out = dict(resp) if isinstance(resp, dict) else {"raw": resp}
            if mid and "messageId" not in out:
                out["messageId"] = mid
            return True, out
        return False, resp

    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        return None

    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._destino(telefone),
            "type": "text",
            "text": {"preview_url": False, "body": mensagem or ""},
        }
        return self._ok_resp(self._post_messages(payload))

    def enviar_template(
        self,
        telefone: str,
        template_name: str,
        language_code: str = "pt_BR",
        template_params: Optional[Any] = None,
        body_params: Optional[List[str]] = None,
    ) -> Tuple[bool, Any]:
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

        template: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code or "pt_BR"},
        }
        if params_list:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": p if str(p).strip() else "-"}
                        for p in params_list
                    ],
                }
            ]
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino(telefone),
            "type": "template",
            "template": template,
        }
        resp = self._post_messages(payload)
        ok, out = self._ok_resp(resp)
        if ok:
            logger.info(
                "[MetaCloud] Template %s enviado para %s (vars=%s)",
                template_name,
                self._destino(telefone),
                len(params_list),
            )
        else:
            logger.error(
                "[MetaCloud] Falha template %s para %s: %s",
                template_name,
                self._destino(telefone),
                str(resp)[:400],
            )
        return ok, out

    def enviar_mensagem_com_botoes_reply(
        self,
        telefone: str,
        mensagem: str,
        button_actions: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        botoes = []
        for i, btn in enumerate((button_actions or [])[:3]):
            label = str(btn.get("label") or btn.get("title") or "")[:20]
            botoes.append(
                {
                    "type": "reply",
                    "reply": {
                        "id": str(btn.get("id") or f"btn_{i}")[:256],
                        "title": label or f"Opção {i + 1}",
                    },
                }
            )
        if not botoes:
            return self.enviar_mensagem_texto_raw(telefone, mensagem)
        interactive: Dict[str, Any] = {
            "type": "button",
            "body": {"text": mensagem or ""},
            "action": {"buttons": botoes},
        }
        if title:
            interactive["header"] = {"type": "text", "text": str(title)[:60]}
        if footer:
            interactive["footer"] = {"text": str(footer)[:60]}
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino(telefone),
            "type": "interactive",
            "interactive": interactive,
        }
        return self._ok_resp(self._post_messages(payload))

    def enviar_lista_opcoes(
        self,
        telefone: str,
        mensagem: str,
        opcoes: List[Dict[str, str]],
        titulo_lista: str = "Opções",
        botao_label: str = "Ver opções",
    ) -> Tuple[bool, Any]:
        rows = []
        for i, op in enumerate((opcoes or [])[:10]):
            rows.append(
                {
                    "id": str(op.get("id") or f"opt_{i}")[:200],
                    "title": str(op.get("title") or op.get("label") or "")[:24],
                    "description": str(op.get("description") or "")[:72],
                }
            )
        if not rows:
            return self.enviar_mensagem_texto_raw(telefone, mensagem)
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino(telefone),
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": mensagem or ""},
                "action": {
                    "button": (botao_label or "Ver opções")[:20],
                    "sections": [{"title": (titulo_lista or "Opções")[:24], "rows": rows}],
                },
            },
        }
        return self._ok_resp(self._post_messages(payload))

    def _decodificar_b64(self, data: str) -> Tuple[bytes, str]:
        raw = data or ""
        mime = "application/octet-stream"
        if raw.startswith("data:") and "base64," in raw:
            header, b64 = raw.split("base64,", 1)
            if ";" in header:
                mime = header[5:].split(";", 1)[0] or mime
            raw = b64
        raw = raw.replace("\r", "").replace("\n", "")
        return base64.b64decode(raw), mime

    def _upload_media(self, blob: bytes, mime: str, filename: str) -> Optional[str]:
        if not self.token or not self.phone_number_id or not blob:
            return None
        try:
            resp = requests.post(
                self._url(f"{self.phone_number_id}/media"),
                headers={"Authorization": f"Bearer {self.token}"},
                files={"file": (filename, blob, mime or "application/octet-stream")},
                data={"messaging_product": "whatsapp", "type": mime or "application/octet-stream"},
                timeout=60,
            )
            data = resp.json() if resp.content else {}
            mid = data.get("id") if isinstance(data, dict) else None
            if resp.status_code not in (200, 201) or not mid:
                logger.error("[MetaCloud] upload media HTTP %s: %s", resp.status_code, str(data)[:300])
                return None
            return str(mid)
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.error("[MetaCloud] upload media failed: %s", exc)
            return None

    def enviar_imagem_b64(
        self, telefone: str, img_b64: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        try:
            blob, mime = self._decodificar_b64(img_b64 or "")
        except (ValueError, TypeError):
            return None
        if not mime.startswith("image/"):
            mime = "image/png"
        media_id = self._upload_media(blob, mime, "image.png")
        if not media_id:
            return None
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino(telefone),
            "type": "image",
            "image": {"id": media_id, "caption": caption or ""},
        }
        ok, resp = self._ok_resp(self._post_messages(payload))
        return resp if ok and isinstance(resp, dict) else None

    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino(telefone),
            "type": "document",
            "document": {
                "link": pdf_url,
                "filename": nome_arquivo or "extrato.pdf",
                "caption": caption or "",
            },
        }
        ok, _resp = self._ok_resp(self._post_messages(payload))
        return ok

    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        try:
            blob, mime = self._decodificar_b64(base64_data or "")
        except (ValueError, TypeError):
            return False
        if mime == "application/octet-stream":
            mime = "application/pdf"
        media_id = self._upload_media(blob, mime, nome_arquivo or "extrato.pdf")
        if not media_id:
            return False
        payload = {
            "messaging_product": "whatsapp",
            "to": self._destino(telefone),
            "type": "document",
            "document": {
                "id": media_id,
                "filename": nome_arquivo or "extrato.pdf",
                "caption": caption or "",
            },
        }
        ok, _resp = self._ok_resp(self._post_messages(payload))
        return ok

    def listar_grupos(self) -> List[Dict[str, str]]:
        return []
