"""Verificação GET (hub.challenge) e HMAC SHA-256 dos webhooks Cloud API."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Optional, Tuple

from django.conf import settings
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


def get_meta_verify_token() -> str:
    return (getattr(settings, "META_CLOUD_VERIFY_TOKEN", None) or "").strip()


def get_meta_app_secret() -> str:
    return (getattr(settings, "META_APP_SECRET", None) or "").strip()


def _query(request: HttpRequest, key: str) -> str:
    if hasattr(request, "query_params"):
        val = request.query_params.get(key) or ""
        if val:
            return str(val)
    if hasattr(request, "GET"):
        return str(request.GET.get(key) or "")
    return ""


def responder_verificacao_webhook_meta(request: HttpRequest) -> Optional[HttpResponse]:
    """
    Responde o handshake da Meta (GET hub.mode=subscribe).
    None se o pedido não for verificação Cloud API.
    """
    mode = _query(request, "hub.mode")
    token = _query(request, "hub.verify_token")
    challenge = _query(request, "hub.challenge")
    if mode != "subscribe" and not token and not challenge:
        return None

    expected = get_meta_verify_token()
    if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected):
        return HttpResponse(challenge or "", content_type="text/plain")

    logger.warning("[MetaWebhook] Verificação GET recusada (mode=%s).", mode)
    return HttpResponse("Forbidden", status=403, content_type="text/plain")


def _payload_cloud_api(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("object") == "whatsapp_business_account":
        return True
    entry = payload.get("entry")
    return isinstance(entry, list) and bool(entry)


def validar_assinatura_meta(
    request: HttpRequest,
    payload: Any,
    *,
    path_token_validado: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Valida X-Hub-Signature-256 em POST Cloud API.

    WhatsAtende no path com token já validado: não exige HMAC (payload reencaminhado).
    Sem App Secret: aceita e registra aviso (dev / transição).
    """
    if path_token_validado:
        return True, None
    if not _payload_cloud_api(payload):
        return True, None

    secret = get_meta_app_secret()
    header = ""
    if hasattr(request, "headers"):
        header = (
            request.headers.get("X-Hub-Signature-256")
            or request.headers.get("X-Hub-Signature")
            or ""
        )
    header = str(header).strip()

    if not secret:
        if header:
            logger.warning(
                "[MetaWebhook] Assinatura presente, mas META_APP_SECRET ausente."
            )
        else:
            logger.warning(
                "[MetaWebhook] POST Cloud API sem META_APP_SECRET — "
                "HMAC não conferido."
            )
        return True, None

    if not header:
        logger.warning("[MetaWebhook] POST Cloud API sem X-Hub-Signature-256.")
        return False, "Assinatura Meta ausente"

    raw = getattr(request, "body", b"") or b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    algo = "sha256"
    hex_digest = header
    if "=" in header:
        algo, hex_digest = header.split("=", 1)
        algo = algo.strip().lower()
        hex_digest = hex_digest.strip()
    if algo != "sha256":
        return False, "Algoritmo de assinatura Meta inválido"

    esperado = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if len(hex_digest) != len(esperado):
        logger.warning("[MetaWebhook] HMAC inválido.")
        return False, "Assinatura Meta inválida"
    if not hmac.compare_digest(hex_digest, esperado):
        logger.warning("[MetaWebhook] HMAC inválido.")
        return False, "Assinatura Meta inválida"
    return True, None
