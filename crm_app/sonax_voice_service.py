"""
Cliente Sonax PABX: click2call e download de gravação (pega_gravacao).

Documentação: https://conteudo.sonax.net.br/kb/pt-br/article/159253/api-de-integracao-de-voz
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings

PROTOCOLO_RE = re.compile(r"PROTOCOLO\s*(\d+)", re.IGNORECASE)
logger = logging.getLogger(__name__)


class SonaxVoiceService:
    def __init__(self) -> None:
        self.click2call_url = getattr(
            settings,
            "SONAX_CLICK2CALL_URL",
            "https://click2call.sonax.net.br/sonax-click2call.php",
        ).rstrip("/")
        if not self.click2call_url.endswith(".php"):
            self.click2call_url = self.click2call_url.rstrip("/")

        self.dbdial_base = getattr(
            settings,
            "SONAX_DBDIAL_BASE_URL",
            "https://api.sonax.net.br/a2billing_v2/admin/Public/dbdial_webapi.php",
        ).rstrip("?")
        self.client_id = str(getattr(settings, "SONAX_ID_CLIENTE", "") or "").strip()
        self.token = str(getattr(settings, "SONAX_CLICK2CALL_TOKEN", "") or "").strip()
        self.integration_token = str(
            getattr(settings, "SONAX_INTEGRATION_TOKEN", "") or self.token
        ).strip()
        self.timeout_seconds = int(getattr(settings, "SONAX_TIMEOUT_SECONDS", 30))

    @property
    def is_click2call_configured(self) -> bool:
        return bool(self.token)

    @property
    def is_recording_download_configured(self) -> bool:
        return bool(self.client_id and self.integration_token)

    def _dbdial_params(self) -> Dict[str, str]:
        return {"id_cliente": self.client_id, "token": self.integration_token}

    @staticmethod
    def _mask_secret(value: str) -> str:
        value = str(value or "")
        if len(value) <= 6:
            return "***"
        return f"{value[:3]}***{value[-3:]}"

    def click_to_call(
        self,
        *,
        destination_digits: str,
        ramal: str,
        var_tags: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if not self.is_click2call_configured:
            raise ValueError("Sonax click2call não configurado: defina SONAX_CLICK2CALL_TOKEN.")

        params: Dict[str, Any] = {
            "numero": destination_digits,
            "ramal": str(ramal).strip(),
            "token": self.token,
            "resposta": "json",
        }
        if var_tags:
            idx = 1
            for key, val in var_tags.items():
                if idx > 5:
                    break
                if val is not None and str(val) != "":
                    params[f"var_{idx}"] = str(val)
                    idx += 1

        url = self.click2call_url
        if not url.endswith("sonax-click2call.php"):
            url = f"{url}/sonax-click2call.php" if ".php" not in url else url

        response = requests.get(url, params=params, timeout=self.timeout_seconds)
        snippet = response.text[:800] if response.text else ""
        debug = {
            "request_url": url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "numero": destination_digits,
            "ramal": str(ramal).strip(),
            "token_mask": self._mask_secret(self.token),
            "response_snippet": snippet,
        }
        if response.status_code >= 400:
            raise RuntimeError(f"Sonax click2call HTTP {response.status_code}: {snippet}")
        if "404 not found" in (response.text or "").lower():
            raise RuntimeError(f"Sonax recusou a chamada: {snippet}")

        parsed = self._parse_click2call_response(response)
        call_id = parsed.get("id_chamada") or parsed.get("protocolo") or parsed.get("id")
        if call_id is None:
            call_id = self._extract_protocol_from_text(response.text or "")
        out: Dict[str, Any] = {"raw_text": response.text, "parsed": parsed, "debug": debug}
        if call_id is not None:
            out["id_chamada"] = str(call_id).strip()
        else:
            logger.warning("Sonax click2call sem id_chamada/protocolo. Debug=%s", debug)
        return out

    @staticmethod
    def _extract_protocol_from_text(text: str) -> Optional[str]:
        raw = text or ""

        # Caso a resposta venha apenas como número entre aspas:
        # ex.: "\"\"19101782792\"\"" (log/Sonax report mostra "Protocolo: 19101782792")
        cleaned = raw.strip().strip('"').strip("'").strip()
        if cleaned.isdigit() and 5 <= len(cleaned) <= 20:
            return cleaned

        m_quote_num = re.search(r'["\']\s*(\d{5,20})\s*["\']', raw)
        if m_quote_num:
            return m_quote_num.group(1)

        # Caso comum do click2call manual (ex.: "Ligação iniciada. ID: 20 | Provedor: sem_id_xxx")
        m_id = re.search(r"\bID\s*:\s*(\d{1,12})\b", raw, flags=re.IGNORECASE)
        if m_id:
            return m_id.group(1)

        m = PROTOCOLO_RE.search(raw)
        if m:
            return m.group(1)

        # Fallback antigo: só captura números se a palavra "PROTOCOLO" aparecer no texto.
        m2 = re.search(r"\b(\d{5,12})\b", raw)
        if m2 and "PROTOCOLO" in raw.upper():
            return m2.group(1)

        return None

    def _parse_click2call_response(self, response: requests.Response) -> Dict[str, Any]:
        text = (response.text or "").strip()
        if not text:
            return {}
        ct = (response.headers.get("content-type") or "").lower()
        if "json" in ct or text.startswith("{") or text.startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    return data
                if isinstance(data, list) and data:
                    return {"lista": data}
            except json.JSONDecodeError:
                pass
        return {"mensagem": text[:2000]}

    def download_recording(self, id_chamada: str, prefer_mp3: Optional[bool] = None) -> Tuple[bytes, str]:
        """
        Baixa gravação via acao=pega_gravacao. Retorna (bytes, extensão .wav ou .mp3).
        Por padrão, prioriza MP3 para facilitar compartilhamento em canais como WhatsApp.
        """
        if not self.is_recording_download_configured:
            raise ValueError(
                "Download de gravação Sonax: defina SONAX_ID_CLIENTE e SONAX_INTEGRATION_TOKEN "
                "(ou o mesmo valor em SONAX_CLICK2CALL_TOKEN)."
            )
        if prefer_mp3 is None:
            prefer_mp3 = bool(getattr(settings, "SONAX_RECORDING_PREFER_MP3", True))
        params = {
            **self._dbdial_params(),
            "acao": "pega_gravacao",
            "id_chamada": str(id_chamada).strip(),
        }
        if prefer_mp3:
            params["recordmp3"] = 1
        response = requests.get(self.dbdial_base, params=params, timeout=self.timeout_seconds * 2)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Sonax pega_gravacao HTTP {response.status_code}: {(response.text or '')[:500]}"
            )
        body = response.content or b""
        if not body:
            raise RuntimeError("Sonax pega_gravacao retornou corpo vazio.")
        if (response.text or "").strip().lower().startswith("404") or b"404 not found" in body[:80].lower():
            raise RuntimeError(f"Sonax pega_gravacao recusou: {(response.text or '')[:500]}")

        ct = (response.headers.get("content-type") or "").lower()

        if body[:2] == b"PK" or "zip" in ct:
            return unpack_recording_zip(body, prefer_mp3=bool(prefer_mp3))

        if "mpeg" in ct or "mp3" in ct:
            return body, ".mp3"
        return body, ".wav"

    def fetch_call_status(self, id_chamada: str) -> Dict[str, Any]:
        """
        Consulta status da chamada via acao=status_chamada.

        Documentação Sonax indica retorno em formato texto com colunas separadas por "|":
        status da ligação | id do ramal | id da fila | data inicio | data final | status atendido |
        duração da chamada | número do ramal | numero discado
        """
        if not self.is_recording_download_configured:
            raise ValueError(
                "Status de chamada Sonax: defina SONAX_ID_CLIENTE e SONAX_INTEGRATION_TOKEN "
                "(ou o mesmo valor em SONAX_CLICK2CALL_TOKEN)."
            )

        params = {
            **self._dbdial_params(),
            "acao": "status_chamada",
            "id_chamada": str(id_chamada).strip(),
        }
        response = requests.get(self.dbdial_base, params=params, timeout=self.timeout_seconds)
        text = (response.text or "").strip()
        if response.status_code >= 400:
            raise RuntimeError(f"Sonax status_chamada HTTP {response.status_code}: {text[:500]}")
        if not text:
            raise RuntimeError("Sonax status_chamada retornou vazio.")
        if text.lower().startswith("404") or "404 not found" in text.lower():
            raise RuntimeError(f"Sonax status_chamada recusou/sem dados: {text[:500]}")

        parsed = _parse_sonax_status_chamada(text)
        parsed["_raw"] = text[:2000]
        return parsed


def unpack_recording_zip(data: bytes, prefer_mp3: bool = False) -> Tuple[bytes, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(zf.namelist())
        first_ext = ".mp3" if prefer_mp3 else ".wav"
        second_ext = ".wav" if prefer_mp3 else ".mp3"
        for ext in (first_ext, second_ext):
            for name in names:
                lower = name.lower()
                if lower.endswith(ext):
                    return zf.read(name), ext
        if names:
            fallback_ext = ".mp3" if names[0].lower().endswith(".mp3") else ".wav"
            return zf.read(names[0]), fallback_ext
    raise RuntimeError("ZIP de gravação Sonax sem arquivos.")


def _parse_sonax_status_chamada(text: str) -> Dict[str, Any]:
    """
    Parser resiliente para resposta do Sonax status_chamada.
    Retorna chaves normalizadas; valores podem ser None quando ausentes.
    """
    raw = (text or "").strip()
    parts = [p.strip() for p in raw.split("|")]
    # Completar até 9 colunas esperadas
    while len(parts) < 9:
        parts.append("")

    status_chamada = parts[0] or ""
    id_ramal = parts[1] or ""
    id_fila = parts[2] or ""
    data_inicio = parts[3] or ""
    data_fim = parts[4] or ""
    status_atendido = parts[5] or ""
    duracao = parts[6] or ""
    numero_ramal = parts[7] or ""
    numero_discado = parts[8] or ""

    # duração pode vir vazia / "0" / float
    duracao_int: Optional[int]
    try:
        duracao_int = int(float(duracao)) if str(duracao).strip() != "" else None
    except (TypeError, ValueError):
        duracao_int = None

    return {
        "status_chamada": status_chamada,
        "status_atendimento": status_atendido,
        "duracao_segundos": duracao_int,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "id_ramal": id_ramal,
        "id_fila": id_fila,
        "numero_ramal": numero_ramal,
        "numero_discado": numero_discado,
    }
