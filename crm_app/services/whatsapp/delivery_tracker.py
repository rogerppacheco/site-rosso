"""
Correlação de DeliveryCallback / MessageStatusCallback com envios aguardando.

messageId da API send ≠ entrega real. Confirmação vem dos webhooks:
- DeliveryCallback: sem `error` = aceito pelo WhatsApp; com `error` = rejeitado
- MessageStatusCallback: SENT/RECEIVED/READ = progresso real na rede
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, Optional, Tuple

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "wa_delivery:"
_DEFAULT_TTL = 180
_DEFAULT_WAIT = 25.0
_POLL_INTERVAL = 0.25
_STATUS_OK = frozenset({"SENT", "RECEIVED", "READ", "READ_BY_ME", "PLAYED"})


def _ttl() -> int:
    return int(getattr(settings, "WHATSAPP_DELIVERY_CACHE_TTL", _DEFAULT_TTL))


def _wait_seconds() -> float:
    return float(getattr(settings, "WHATSAPP_DELIVERY_WAIT_SECONDS", _DEFAULT_WAIT))


def _ids_from_payload(data: Dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("messageId", "zaapId", "id"):
        val = data.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s and s not in ids:
            ids.append(s)
    raw_ids = data.get("ids")
    if isinstance(raw_ids, list):
        for val in raw_ids:
            s = str(val).strip() if val is not None else ""
            if s and s not in ids:
                ids.append(s)
    elif raw_ids is not None:
        s = str(raw_ids).strip()
        if s and s not in ids:
            ids.append(s)
    return ids


def _cache_key(message_id: str) -> str:
    return f"{_CACHE_PREFIX}{message_id}"


def registrar_resultado_entrega(
    message_ids: Iterable[str],
    *,
    ok: bool,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    phone: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    """Grava resultado para todos os IDs (messageId e zaapId podem diferir)."""
    payload = {
        "ok": bool(ok),
        "error": (error or "").strip() or None,
        "error_code": (error_code or "").strip() or None,
        "phone": (phone or "").strip() or None,
        "source": (source or "").strip() or None,
    }
    ttl = _ttl()
    for mid in message_ids:
        if not mid:
            continue
        prev = cache.get(_cache_key(str(mid)))
        # Não sobrescrever falha já registrada com um sucesso posterior ambíguo.
        if isinstance(prev, dict) and prev.get("ok") is False and payload["ok"]:
            continue
        cache.set(_cache_key(str(mid)), payload, timeout=ttl)
    logger.info(
        "[DeliveryTracker] resultado ok=%s ids=%s error=%s code=%s phone=%s source=%s",
        payload["ok"],
        list(message_ids),
        payload["error"],
        payload["error_code"],
        payload["phone"],
        payload["source"],
    )


def processar_delivery_callback(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processa payload type=DeliveryCallback.
    Sucesso = ausência de `error`; falha = `error` presente.
    """
    ids = _ids_from_payload(data)
    error = data.get("error")
    error_code = data.get("errorCode") or data.get("error_code")
    phone = str(data.get("phone") or "")
    ok = not bool(error)
    if not ids:
        logger.warning(
            "[DeliveryTracker] DeliveryCallback sem messageId/zaapId phone=%s",
            phone,
        )
        return {"status": "ok", "mensagem": "DeliveryCallback sem id"}

    registrar_resultado_entrega(
        ids,
        ok=ok,
        error=str(error) if error else None,
        error_code=str(error_code) if error_code else None,
        phone=phone or None,
        source="DeliveryCallback",
    )
    return {
        "status": "ok",
        "mensagem": "DeliveryCallback processado",
        "ok": ok,
        "ids": ids,
    }


def processar_message_status_callback(data: Dict[str, Any]) -> Dict[str, Any]:
    """Processa MessageStatusCallback (SENT/RECEIVED/READ...)."""
    ids = _ids_from_payload(data)
    status_msg = str(data.get("status") or "").strip().upper()
    phone = str(data.get("phone") or "")
    if not ids:
        logger.warning(
            "[DeliveryTracker] MessageStatus sem ids status=%s phone=%s",
            status_msg,
            phone,
        )
        return {"status": "ok", "mensagem": "MessageStatus sem id"}

    if status_msg in _STATUS_OK:
        registrar_resultado_entrega(
            ids,
            ok=True,
            phone=phone or None,
            source=f"MessageStatus:{status_msg}",
        )
        return {
            "status": "ok",
            "mensagem": "MessageStatus processado",
            "ok": True,
            "ids": ids,
            "wa_status": status_msg,
        }

    logger.info(
        "[DeliveryTracker] MessageStatus ignorado status=%s ids=%s",
        status_msg,
        ids,
    )
    return {
        "status": "ok",
        "mensagem": f"MessageStatus {status_msg or 'vazio'} ignorado",
        "ok": None,
        "ids": ids,
    }


def obter_resultado(message_id: str) -> Optional[Dict[str, Any]]:
    if not message_id:
        return None
    val = cache.get(_cache_key(str(message_id)))
    return val if isinstance(val, dict) else None


def aguardar_entrega(
    *message_ids: str,
    timeout: Optional[float] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Espera DeliveryCallback ou MessageStatus correlacionado a qualquer ID.

    Returns:
        (True, result) se entregue sem error;
        (False, result) se callback com error;
        (False, None) se timeout sem callback.
    """
    ids = [str(i).strip() for i in message_ids if i and str(i).strip()]
    if not ids:
        return False, None

    deadline = time.monotonic() + (timeout if timeout is not None else _wait_seconds())
    while True:
        for mid in ids:
            result = obter_resultado(mid)
            if result is not None:
                return bool(result.get("ok")), result
        if time.monotonic() >= deadline:
            logger.warning(
                "[DeliveryTracker] timeout aguardando entrega ids=%s",
                ids,
            )
            return False, None
        time.sleep(_POLL_INTERVAL)
