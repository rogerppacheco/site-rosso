"""Provider Evolution API (Baileys)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.phone_utils import destino_evolution, formatar_telefone_br

logger = logging.getLogger(__name__)

DEFAULT_INSTANCE = "site_record_zap"


class EvolutionProvider(WhatsAppProvider):
    def __init__(self) -> None:
        self.base_url = (os.environ.get("EVOLUTION_API_URL") or "").rstrip("/")
        self.api_key = os.environ.get("EVOLUTION_API_KEY", "")
        self.instance_name = os.environ.get("EVOLUTION_INSTANCE_NAME", DEFAULT_INSTANCE)
        if not self.base_url or not self.api_key:
            logger.error(
                "Evolution CRITICO: EVOLUTION_API_URL / EVOLUTION_API_KEY não configurados"
            )

    def _headers(self) -> Dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Any:
        url = f"{self.base_url}{path}"
        logger.debug("[Evolution] %s %s", method, url)
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
                    "[Evolution] HTTP %s %s: %s",
                    resp.status_code,
                    path,
                    resp.text[:500],
                )
                try:
                    return resp.json()
                except ValueError:
                    return None
            try:
                return resp.json()
            except ValueError:
                return resp.text
        except requests.exceptions.RequestException as exc:
            logger.error("[Evolution] Request failed %s: %s", path, exc)
            return None

    def _message_id(self, resp: Any) -> Optional[str]:
        if not isinstance(resp, dict):
            return None
        if resp.get("messageId") or resp.get("id"):
            return str(resp.get("messageId") or resp.get("id"))
        key = resp.get("key")
        if isinstance(key, dict) and key.get("id"):
            return str(key["id"])
        data = resp.get("data")
        if isinstance(data, dict):
            k = data.get("key")
            if isinstance(k, dict) and k.get("id"):
                return str(k["id"])
        return None

    def _normalize_success(self, resp: Any) -> Dict[str, Any]:
        if isinstance(resp, dict):
            mid = self._message_id(resp)
            if mid:
                return {"messageId": mid, **resp}
            return resp
        return {"raw": resp}

    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        if not self.base_url or not self.api_key:
            return True
        numero = formatar_telefone_br(telefone)
        path = f"/chat/whatsappNumbers/{self.instance_name}"
        data = self._request("POST", path, {"numbers": [numero]})
        if not isinstance(data, dict):
            return None
        items = data.get("response") or data.get("numbers") or data.get("data") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                jid = str(item.get("jid") or item.get("number") or "")
                if numero in jid.replace("@s.whatsapp.net", ""):
                    exists = item.get("exists")
                    if exists is not None:
                        return bool(exists)
                    return True
        if data.get("error"):
            return None
        return True

    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        path = f"/message/sendText/{self.instance_name}"
        payload = {"number": destino_evolution(telefone), "text": mensagem}
        resp = self._request("POST", path, payload)
        if resp and not (isinstance(resp, dict) and resp.get("error")):
            return True, self._normalize_success(resp)
        return False, resp or "Erro ao enviar - resposta vazia"

    def enviar_mensagem_com_botoes_reply(
        self,
        telefone: str,
        mensagem: str,
        button_actions: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        if not button_actions:
            return False, None
        buttons = []
        for action in button_actions:
            buttons.append(
                {
                    "type": "reply",
                    "displayText": action.get("label") or action.get("text") or "OK",
                    "id": action.get("id") or action.get("buttonId") or "btn",
                }
            )
        path = f"/message/sendButtons/{self.instance_name}"
        payload: Dict[str, Any] = {
            "number": destino_evolution(telefone),
            "title": title or "",
            "description": (mensagem or "").strip(),
            "footer": footer or "",
            "buttons": buttons,
        }
        resp = self._request("POST", path, payload)
        if isinstance(resp, dict) and resp.get("error"):
            logger.warning("[Evolution] sendButtons erro: %s", resp)
            return False, None
        if resp and self.resposta_indica_sucesso(resp if isinstance(resp, dict) else {}):
            return True, self._normalize_success(resp)
        return False, None

    def enviar_imagem_b64(
        self, telefone: str, img_b64: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        if "base64," in img_b64:
            media = img_b64
        else:
            media = f"data:image/png;base64,{img_b64}"
        path = f"/message/sendMedia/{self.instance_name}"
        payload = {
            "number": destino_evolution(telefone),
            "mediatype": "image",
            "mimetype": "image/png",
            "media": media,
            "caption": caption or "",
        }
        resp = self._request("POST", path, payload, timeout=60)
        if isinstance(resp, dict) and resp.get("error"):
            return None
        if resp and self.resposta_indica_sucesso(resp if isinstance(resp, dict) else {}):
            return self._normalize_success(resp)
        return None

    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        path = f"/message/sendMedia/{self.instance_name}"
        payload: Dict[str, Any] = {
            "number": destino_evolution(telefone),
            "mediatype": "document",
            "mimetype": "application/pdf",
            "media": pdf_url,
            "fileName": nome_arquivo,
            "caption": caption or "",
            "delay": 1200,
        }
        resp = self._request("POST", path, payload, timeout=60)
        if isinstance(resp, dict) and resp.get("error"):
            return False
        return bool(resp and self.resposta_indica_sucesso(resp if isinstance(resp, dict) else {}))

    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        if base64_data.startswith("data:") and "base64," in base64_data:
            b64 = base64_data.split("base64,", 1)[1]
        else:
            b64 = base64_data
        b64 = b64.replace("\r", "").replace("\n", "")
        media = f"data:application/pdf;base64,{b64}"
        path = f"/message/sendMedia/{self.instance_name}"
        payload: Dict[str, Any] = {
            "number": destino_evolution(telefone),
            "mediatype": "document",
            "mimetype": "application/pdf",
            "media": media,
            "fileName": nome_arquivo,
            "caption": caption or "",
            "delay": 1200,
        }
        resp = self._request("POST", path, payload, timeout=60)
        if isinstance(resp, dict) and resp.get("error"):
            return False
        return bool(resp and self.resposta_indica_sucesso(resp if isinstance(resp, dict) else {}))

    def listar_grupos(self) -> List[Dict[str, str]]:
        path = f"/group/fetchAllGroups/{self.instance_name}?getParticipants=false"
        data = self._request("GET", path, timeout=45)
        grupos_raw: List[Any] = []
        if isinstance(data, list):
            grupos_raw = data
        elif isinstance(data, dict):
            grupos_raw = (
                data.get("groups")
                or data.get("response")
                or data.get("data")
                or []
            )
            if isinstance(grupos_raw, dict):
                grupos_raw = list(grupos_raw.values())

        lista: List[Dict[str, str]] = []
        seen: set[str] = set()
        for g in grupos_raw:
            if not isinstance(g, dict):
                continue
            gid = g.get("id") or g.get("jid") or g.get("groupId")
            if not gid:
                continue
            gid_str = str(gid)
            if "@g.us" not in gid_str and gid_str.isdigit():
                gid_str = f"{gid_str}-group"
            elif "@g.us" in gid_str:
                gid_str = gid_str.split("@g.us")[0] + "-group"
            if gid_str in seen:
                continue
            seen.add(gid_str)
            nome = g.get("subject") or g.get("name") or "Sem Nome"
            lista.append({"id": gid_str, "name": str(nome)})
        return lista

    def baixar_midia_base64(self, evolution_message: Dict[str, Any]) -> Optional[str]:
        """Baixa mídia de mensagem inbound via Evolution getBase64FromMediaMessage."""
        path = f"/chat/getBase64FromMediaMessage/{self.instance_name}"
        payload = {"message": evolution_message, "convertToMp4": False}
        data = self._request("POST", path, payload, timeout=60)
        if not isinstance(data, dict):
            return None
        b64 = data.get("base64") or (data.get("data") or {}).get("base64")
        if isinstance(b64, str) and b64:
            return b64
        return None
