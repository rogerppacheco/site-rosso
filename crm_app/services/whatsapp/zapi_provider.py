"""Provider Z-API (legado / rollback)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.phone_utils import destino_zapi, formatar_telefone_br

logger = logging.getLogger(__name__)


class ZapiProvider(WhatsAppProvider):
    def __init__(self) -> None:
        self.instance_id = os.environ.get("ZAPI_INSTANCE_ID", "")
        self.token = os.environ.get("ZAPI_TOKEN", "")
        self.client_token = os.environ.get("ZAPI_CLIENT_TOKEN", "")
        self.base_url = (
            f"https://api.z-api.io/instances/{self.instance_id}/token/{self.token}"
        )
        if not self.instance_id or not self.token:
            logger.error("Z-API CRITICO: Credenciais não encontradas nas variáveis de ambiente!")

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.client_token:
            headers["client-token"] = self.client_token
        return headers

    def _send_request(
        self, url: str, payload: Optional[Dict[str, Any]] = None, method: str = "POST"
    ) -> Any:
        logger.debug("[Z-API] %s %s", method, url)
        if payload and logger.isEnabledFor(logging.DEBUG):
            if "document" in payload and isinstance(payload.get("document"), str):
                payload_log = payload.copy()
                payload_log["document"] = f"[BASE64: {len(payload['document'])} chars]"
                logger.debug("[Z-API] Payload: %s", payload_log)
            else:
                logger.debug("[Z-API] Payload: %s", payload)

        try:
            timeout_val = 60 if "send-document" in url else (15 if method == "GET" else 30)
            method_u = (method or "POST").upper()
            if method_u == "GET":
                response = requests.get(url, headers=self._get_headers(), timeout=timeout_val)
            elif method_u == "PUT":
                response = requests.put(
                    url, json=payload, headers=self._get_headers(), timeout=timeout_val
                )
            else:
                response = requests.post(
                    url, json=payload, headers=self._get_headers(), timeout=timeout_val
                )

            if response.status_code not in (200, 201):
                logger.error("[Z-API] Erro HTTP %s: %s", response.status_code, response.text)
                try:
                    return response.json()
                except ValueError:
                    return None
            try:
                return response.json()
            except ValueError:
                return response.text
        except requests.exceptions.RequestException as exc:
            logger.error("[Z-API] Request Exception: %s", exc)
            return None

    def configurar_webhook_delivery(self, callback_url: str) -> bool:
        """Configura receivedAndDelivery / On-send (DeliveryCallback) na instância."""
        url = f"{self.base_url}/update-webhook-delivery"
        resp = self._send_request(url, {"value": callback_url}, method="PUT")
        ok = bool(isinstance(resp, dict) and resp.get("value") is True)
        if ok:
            logger.info("[Z-API] Webhook delivery configurado: %s", callback_url)
        else:
            logger.error("[Z-API] Falha ao configurar webhook delivery: %s", resp)
        return ok

    def obter_dados_instancia(self) -> Optional[Dict[str, Any]]:
        data = self._send_request(f"{self.base_url}/me", method="GET")
        return data if isinstance(data, dict) else None

    def _normalizar_phone_exists_payload(self, data: Any) -> Optional[Dict[str, Any]]:
        """Z-API pode devolver objeto único ou lista [{exists, phone, lid}]."""
        if isinstance(data, list) and data:
            first = data[0]
            return first if isinstance(first, dict) else None
        if isinstance(data, dict):
            return data
        return None

    def consultar_phone_exists(self, telefone: str) -> Optional[Dict[str, Any]]:
        """Consulta phone-exists e devolve o payload canônico (exists/phone/lid)."""
        telefone_limpo = formatar_telefone_br(telefone)
        if not self.instance_id or not self.token:
            return {"exists": True, "phone": telefone_limpo, "lid": None}

        url = f"{self.base_url}/phone-exists/{telefone_limpo}"
        data = self._send_request(url, method="GET")
        info = self._normalizar_phone_exists_payload(data)
        if not info:
            return None
        if info.get("error") or info.get("statusCode", 200) != 200:
            logger.warning(
                "[Z-API] Erro ao verificar número %s: %s",
                telefone_limpo,
                info.get("message", info.get("error")),
            )
            return None
        return info

    def resolver_destino_envio(self, telefone: str) -> str:
        """
        Destino real do WhatsApp.

        No Brasil o CRM guarda o 9º dígito, mas o JID interno frequentemente
        vem sem ele (ex.: 5531988832369 → 553188832369). Enviar no formato
        errado gera messageId fantasma sem aparecer no WhatsApp Web.
        """
        bruto = destino_zapi(telefone)
        if not bruto:
            return ""
        if "-group" in bruto or ("-" in bruto and bruto.replace("-", "").isdigit()):
            return bruto

        info = self.consultar_phone_exists(telefone)
        if not info or info.get("exists") is False:
            return bruto

        phone_wa = "".join(filter(str.isdigit, str(info.get("phone") or "")))
        lid = str(info.get("lid") or "").strip()
        if phone_wa:
            if phone_wa != "".join(filter(str.isdigit, bruto)):
                logger.info(
                    "[Z-API] Destino canônico %s → %s (lid=%s)",
                    bruto,
                    phone_wa,
                    lid or "-",
                )
            return phone_wa
        if lid:
            return lid if "@lid" in lid else f"{lid}@lid"
        return bruto

    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        if not self.instance_id or not self.token:
            return True
        info = self.consultar_phone_exists(telefone)
        if info is None:
            return None
        return bool(info.get("exists", False))

    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        url = f"{self.base_url}/send-text"
        telefone_limpo = self.resolver_destino_envio(telefone)
        payload = {"phone": telefone_limpo, "message": mensagem}
        resp = self._send_request(url, payload)
        if self.resposta_indica_sucesso(resp):
            message_id = (
                (resp or {}).get("messageId")
                or (resp or {}).get("zaapId")
                or (resp or {}).get("id")
            )
            logger.info(
                "[Z-API] Texto enviado para %s messageId=%s",
                telefone_limpo,
                message_id,
            )
            return True, resp
        erro = resp
        if isinstance(resp, dict):
            erro = resp.get("message") or resp.get("error") or resp
        logger.error(
            "[Z-API] Falha ao enviar texto para %s: %s",
            telefone_limpo,
            erro,
        )
        return False, erro if erro is not None else "Erro ao enviar - resposta vazia"

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
        url = f"{self.base_url}/send-button-actions"
        telefone_limpo = self.resolver_destino_envio(telefone)
        payload: Dict[str, Any] = {
            "phone": telefone_limpo,
            "message": (mensagem or "").strip(),
            "buttonActions": button_actions,
        }
        if title:
            payload["title"] = title
        if footer:
            payload["footer"] = footer
        resp = self._send_request(url, payload)
        if not resp or not isinstance(resp, dict):
            return False, None
        if resp.get("error"):
            return False, None
        if self.resposta_indica_sucesso(resp):
            return True, resp
        return False, None

    def enviar_lista_opcoes(
        self,
        telefone: str,
        mensagem: str,
        opcoes: List[Dict[str, str]],
        titulo_lista: str = "Opções",
        botao_label: str = "Ver opções",
    ) -> Tuple[bool, Any]:
        """Envia lista interativa via /send-option-list (máx. ~10 itens)."""
        if not opcoes:
            return False, None
        # WhatsApp costuma limitar títulos a 24 chars e ~10 opções
        options_payload = []
        for opt in opcoes[:10]:
            title = str(opt.get("title") or "")[:24]
            options_payload.append(
                {
                    "id": str(opt.get("id") or title)[:200],
                    "title": title,
                    "description": str(opt.get("description") or "")[:72],
                }
            )
        url = f"{self.base_url}/send-option-list"
        telefone_limpo = self.resolver_destino_envio(telefone)
        payload: Dict[str, Any] = {
            "phone": telefone_limpo,
            "message": (mensagem or "").strip(),
            "optionList": {
                "title": (titulo_lista or "Opções")[:60],
                "buttonLabel": (botao_label or "Ver opções")[:20],
                "options": options_payload,
            },
        }
        resp = self._send_request(url, payload)
        if not resp or not isinstance(resp, dict):
            return False, None
        if resp.get("error"):
            return False, None
        if self.resposta_indica_sucesso(resp):
            return True, resp
        return False, None

    def enviar_imagem_b64(
        self, telefone: str, img_b64: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/send-image"
        telefone_limpo = self.resolver_destino_envio(telefone)
        if "base64," not in img_b64:
            img_b64 = "data:image/png;base64," + img_b64
        payload = {"phone": telefone_limpo, "image": img_b64, "caption": caption or ""}
        resp = self._send_request(url, payload)
        if not resp or not isinstance(resp, dict):
            return None
        if resp.get("error"):
            return None
        if self.resposta_indica_sucesso(resp):
            return resp
        return None

    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        extensao = nome_arquivo.split(".")[-1].lower() if "." in nome_arquivo else "pdf"
        url = f"{self.base_url}/send-document/{extensao}"
        telefone_limpo = self.resolver_destino_envio(telefone)
        payload: Dict[str, Any] = {
            "phone": telefone_limpo,
            "document": pdf_url,
            "fileName": nome_arquivo,
        }
        if caption:
            payload["caption"] = caption
        resp = self._send_request(url, payload)
        if isinstance(resp, dict) and resp.get("error"):
            return False
        return bool(resp and self.resposta_indica_sucesso(resp))

    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        extensao = nome_arquivo.split(".")[-1].lower() if "." in nome_arquivo else "pdf"
        url = f"{self.base_url}/send-document/{extensao}"
        telefone_limpo = self.resolver_destino_envio(telefone)

        if base64_data.startswith("data:") and "base64," in base64_data:
            base64_data = base64_data.split("base64,", 1)[1]
        base64_data = base64_data.replace("\r", "").replace("\n", "")
        document_value = f"data:application/pdf;base64,{base64_data}"

        payload: Dict[str, Any] = {
            "phone": telefone_limpo,
            "document": document_value,
            "fileName": nome_arquivo,
        }
        if caption:
            payload["caption"] = caption
        resp = self._send_request(url, payload)
        if isinstance(resp, dict) and resp.get("error"):
            return False
        return bool(resp and self.resposta_indica_sucesso(resp))

    def listar_grupos(self) -> List[Dict[str, str]]:
        page_size = 100
        page = 1
        todos: List[Any] = []
        url_com_params = f"{self.base_url}/groups?page={page}&pageSize={page_size}"
        data = self._send_request(url_com_params, method="GET")
        if not data or (isinstance(data, dict) and "error" in data):
            data = self._send_request(f"{self.base_url}/groups", method="GET")
        if data:
            if isinstance(data, list):
                todos = data
            elif isinstance(data, dict) and "response" in data:
                r = data["response"]
                todos = r if isinstance(r, list) else []
            elif isinstance(data, dict) and "groups" in data:
                g = data["groups"]
                todos = g if isinstance(g, list) else []

        if todos and len(todos) == page_size:
            page = 2
            while page <= 50:
                chunk_data = self._send_request(
                    f"{self.base_url}/groups?page={page}&pageSize={page_size}",
                    method="GET",
                )
                chunk: List[Any] = []
                if chunk_data:
                    if isinstance(chunk_data, list):
                        chunk = chunk_data
                    elif isinstance(chunk_data, dict) and "response" in chunk_data:
                        r = chunk_data["response"]
                        chunk = r if isinstance(r, list) else []
                    elif isinstance(chunk_data, dict) and "groups" in chunk_data:
                        g = chunk_data["groups"]
                        chunk = g if isinstance(g, list) else []
                if not chunk:
                    break
                todos.extend(chunk)
                if len(chunk) < page_size:
                    break
                page += 1

        seen: set[str] = set()
        lista_formatada: List[Dict[str, str]] = []
        for g in todos:
            if not isinstance(g, dict):
                continue
            g_id = g.get("id") or g.get("phone") or g.get("chatId")
            if not g_id or g_id in seen:
                continue
            seen.add(str(g_id))
            g_name = g.get("name") or g.get("subject") or g.get("contactName") or "Sem Nome"
            lista_formatada.append({"id": str(g_id), "name": g_name})
        return lista_formatada
