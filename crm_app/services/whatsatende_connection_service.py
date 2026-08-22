"""Proxy WhatsAtende para status, QR Code e desconexão (painel admin)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.app14.whatsatende.com.br"


class WhatsAtendeConnectionError(Exception):
    """Falha ao comunicar com a API WhatsAtende."""


class WhatsAtendeConnectionService:
    def __init__(self) -> None:
        self.base_url = (
            getattr(settings, "WHATSATENDE_API_URL", None) or DEFAULT_API_URL
        ).rstrip("/")
        self.token = (getattr(settings, "WHATSATENDE_TOKEN", None) or "").strip()
        self.whatsapp_id = str(
            getattr(settings, "WHATSATENDE_WHATSAPP_ID", None) or ""
        ).strip()

    def ensure_configured(self) -> None:
        if not self.token:
            raise WhatsAtendeConnectionError(
                "WhatsAtende não configurada (WHATSATENDE_TOKEN)"
            )
        if not self.whatsapp_id:
            raise WhatsAtendeConnectionError(
                "WhatsAtende sem WHATSATENDE_WHATSAPP_ID "
                "(ID da conexão no painel Conexões)"
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        self.ensure_configured()
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text}
            if resp.status_code not in (200, 201):
                logger.error(
                    "WhatsAtende %s %s HTTP %s: %s",
                    method,
                    path,
                    resp.status_code,
                    str(data)[:500],
                )
                raise WhatsAtendeConnectionError(
                    "Não foi possível comunicar com a WhatsAtende"
                )
            return data if isinstance(data, dict) else {"data": data}
        except requests.exceptions.RequestException as exc:
            logger.error("WhatsAtende %s %s falhou: %s", method, path, exc)
            raise WhatsAtendeConnectionError(
                "Não foi possível comunicar com a WhatsAtende"
            ) from exc

    def get_status(self) -> Dict[str, Any]:
        path = f"/api/messages/checkStatus/{self.whatsapp_id}"
        data = self._request("GET", path)
        state_raw = (
            data.get("status")
            or data.get("state")
            or data.get("connectionStatus")
            or (data.get("whatsapp") or {}).get("status")
            or ""
        )
        state_l = str(state_raw).strip().lower()
        if state_l in ("qrcode", "connecting", "pairing"):
            mapped = "connecting"
            connected = False
        elif state_l in (
            "open",
            "connected",
            "online",
            "conectado",
            "authenticated",
        ):
            mapped = "open"
            connected = True
        elif state_l in ("close", "closed", "disconnected", "desconectado", "logout"):
            mapped = "close"
            connected = False
        else:
            mapped = state_l or "unknown"
            connected = False
        return {
            "connected": connected,
            "state": mapped,
            "rawState": state_raw,
            "instanceName": self.whatsapp_id,
            "provider": "whatsatende",
            "data": data,
        }

    def get_qrcode(self) -> Dict[str, Any]:
        path = f"/api/messages/getQrCode/{self.whatsapp_id}"
        data = self._request("POST", path, {})
        qr = (
            data.get("qrcode")
            or data.get("base64")
            or data.get("code")
            or (data.get("data") or {}).get("qrcode")
            or (data.get("data") or {}).get("base64")
        )
        if isinstance(qr, dict):
            qr = qr.get("base64") or qr.get("code") or qr.get("qrcode")
        if isinstance(qr, str) and qr and not qr.startswith("data:"):
            # Pode ser base64 puro ou string do QR
            if qr.startswith("http"):
                return {"qrcode": qr, "format": "url", "data": data}
            qr_img = f"data:image/png;base64,{qr}"
            return {"qrcode": qr_img, "format": "base64", "data": data}
        if isinstance(qr, str) and qr.startswith("data:"):
            return {"qrcode": qr, "format": "base64", "data": data}
        return {"qrcode": qr, "format": "unknown", "data": data}

    def disconnect(self) -> Dict[str, Any]:
        path = f"/api/messages/disconnect/{self.whatsapp_id}"
        data = self._request("POST", path, {})
        return {"ok": True, "data": data, "provider": "whatsatende"}

    def start_session(self) -> Dict[str, Any]:
        path = f"/api/messages/startSession/{self.whatsapp_id}"
        data = self._request("POST", path, {})
        return {"ok": True, "data": data, "provider": "whatsatende"}
