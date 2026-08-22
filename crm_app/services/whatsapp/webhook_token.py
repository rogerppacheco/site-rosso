"""Validação de token no path/query do webhook WhatsApp (WhatsAtende)."""
from __future__ import annotations

import hmac
import logging
from typing import Any, Optional, Tuple

from django.conf import settings
from django.http import HttpRequest

logger = logging.getLogger(__name__)


def get_whatsatende_webhook_token() -> str:
    return (
        getattr(settings, "WHATSATENDE_WEBHOOK_TOKEN", None)
        or ""
    ).strip()


def extrair_token_webhook(
    request: HttpRequest,
    path_token: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Retorna (token, origem).
    Origem: path | query | header | ''.
    """
    if path_token and str(path_token).strip():
        return str(path_token).strip(), "path"

    q = ""
    if hasattr(request, "query_params"):
        q = (
            request.query_params.get("token")
            or request.query_params.get("secret")
            or ""
        )
    elif hasattr(request, "GET"):
        q = request.GET.get("token") or request.GET.get("secret") or ""
    if q and str(q).strip():
        return str(q).strip(), "query"

    header = ""
    if hasattr(request, "headers"):
        header = (
            request.headers.get("X-Webhook-Token")
            or request.headers.get("X-Webhook-Secret")
            or ""
        )
    if header and str(header).strip():
        return str(header).strip(), "header"

    return "", ""


def validar_token_webhook_whatsatende(
    request: HttpRequest,
    path_token: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Valida token quando a rota traz token no path OU quando query/header
    enviam token e WHATSATENDE_WEBHOOK_TOKEN está configurado.

    - Rota sem token (Z-API/Evolution legado): libera (compatibilidade).
    - Rota com token / query / header: exige match com WHATSATENDE_WEBHOOK_TOKEN.
    - Token no path/query sem secret configurado no servidor: 403.

    Retorna (ok, mensagem_erro_ou_None).
    """
    expected = get_whatsatende_webhook_token()
    received, origem = extrair_token_webhook(request, path_token=path_token)

    # URL clássica sem token → Z-API / Evolution continuam funcionando
    if not received:
        return True, None

    if not expected:
        logger.warning(
            "[WebhookWhatsApp] Token recebido via %s, mas "
            "WHATSATENDE_WEBHOOK_TOKEN não está configurado.",
            origem or "desconhecida",
        )
        return False, "Webhook token não configurado no servidor"

    if not hmac.compare_digest(received, expected):
        logger.warning(
            "[WebhookWhatsApp] Token inválido (origem=%s path=%s).",
            origem,
            getattr(request, "path", ""),
        )
        return False, "Webhook token inválido"

    return True, None


def montar_url_webhook_whatsatende(site_url: Optional[str] = None) -> str:
    """URL sugerida para cadastrar na WhatsAtende (com token no path, se houver)."""
    base = (site_url or getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if not base:
        base = "https://www.recordpap.com.br"
    token = get_whatsatende_webhook_token()
    if token:
        return f"{base}/api/crm/webhook-whatsapp/{token}/"
    return f"{base}/api/crm/webhook-whatsapp/"
