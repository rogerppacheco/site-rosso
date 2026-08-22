import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ZenviaVoiceService:
    """
    Cliente simples da API de voz da Zenvia/TotalVoice.
    Endpoints são configuráveis para permitir ajuste fino sem mudar código.
    """

    def __init__(self) -> None:
        self.base_url = getattr(settings, "ZENVIA_VOICE_API_URL", "https://voice-api.zenvia.com").rstrip("/")
        self.access_token = getattr(settings, "ZENVIA_VOICE_ACCESS_TOKEN", "")
        self.calls_endpoint = getattr(settings, "ZENVIA_VOICE_CALLS_ENDPOINT", "/chamada")
        self.recording_endpoint_template = getattr(
            settings,
            "ZENVIA_VOICE_RECORDING_ENDPOINT_TEMPLATE",
            "/chamada/{call_id}/gravacao",
        )
        self.timeout_seconds = int(getattr(settings, "ZENVIA_VOICE_TIMEOUT_SECONDS", 20))

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Access-Token": self.access_token,
        }

    def create_call(
        self,
        *,
        source_number: str,
        destination_number: str,
        record_audio: bool = True,
        tags: str = "",
        bina: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cria chamada de voz.
        Observação: o payload pode variar por conta/plano. Campos opcionais são enviados só quando preenchidos.
        """
        if not self.is_configured:
            raise ValueError("Zenvia Voice não configurada: defina ZENVIA_VOICE_ACCESS_TOKEN.")

        payload: Dict[str, Any] = {
            "numero_origem": source_number,
            "numero_destino": destination_number,
            "gravar_audio": bool(record_audio),
        }
        if tags:
            payload["tags"] = tags
        if bina:
            payload["bina"] = bina

        url = f"{self.base_url}{self.calls_endpoint}"
        response = requests.post(
            url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        self._raise_for_status(response, "criar chamada")
        return response.json()

    def fetch_call(self, call_id: str) -> Dict[str, Any]:
        if not self.is_configured:
            raise ValueError("Zenvia Voice não configurada: defina ZENVIA_VOICE_ACCESS_TOKEN.")
        url = f"{self.base_url}{self.calls_endpoint}/{call_id}"
        response = requests.get(url, headers=self._headers(), timeout=self.timeout_seconds)
        self._raise_for_status(response, "buscar chamada")
        return response.json()

    def fetch_recording(self, call_id: str) -> Dict[str, Any]:
        if not self.is_configured:
            raise ValueError("Zenvia Voice não configurada: defina ZENVIA_VOICE_ACCESS_TOKEN.")
        endpoint = self.recording_endpoint_template.format(call_id=call_id)
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, headers=self._headers(), timeout=self.timeout_seconds)
        self._raise_for_status(response, "buscar gravação")
        return response.json()

    @staticmethod
    def _raise_for_status(response: requests.Response, action: str) -> None:
        if response.status_code >= 400:
            snippet = response.text[:500]
            raise RuntimeError(f"Falha ao {action} na Zenvia ({response.status_code}): {snippet}")

