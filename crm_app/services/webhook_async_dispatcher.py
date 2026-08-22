"""
Despacho assíncrono de webhooks Z-API — libera o worker Gunicorn imediatamente.

Com WHATSAPP_USE_DEDICATED_WORKER=True no web, enfileira em PostgreSQL.
Caso contrário, processamento pesado roda em thread daemon no mesmo container.
"""
from __future__ import annotations

import copy
import logging
import threading
from typing import Any, Dict, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class WebhookRequestContext:
    """Substituto mínimo de HttpRequest para build_absolute_uri em background."""

    def __init__(self, request: Any = None) -> None:
        if request is not None:
            self._base = request.build_absolute_uri("/").rstrip("/")
        else:
            domain = getattr(settings, "RAILWAY_PUBLIC_DOMAIN", None) or "www.recordpap.com.br"
            self._base = f"https://{domain}"

    def build_absolute_uri(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self._base}{path}"


def webhook_usa_fila_dedicada() -> bool:
    return bool(
        getattr(settings, "WHATSAPP_USE_DEDICATED_WORKER", False)
        and not getattr(settings, "WHATSAPP_WORKER_MODE", False)
    )


def _nome_thread(payload: Dict[str, Any]) -> str:
    phone = (
        payload.get("phone")
        or payload.get("from")
        or payload.get("phoneNumber")
        or "unknown"
    )
    return f"webhook-{str(phone)[-8:]}"


def _base_url_de_request(request: Any = None) -> str:
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    domain = getattr(settings, "RAILWAY_PUBLIC_DOMAIN", None) or "www.recordpap.com.br"
    return f"https://{domain}"


def _worker_processar(payload: Dict[str, Any], ctx: WebhookRequestContext) -> None:
    import django.db

    try:
        django.db.close_old_connections()
        from crm_app.whatsapp_webhook_handler import processar_webhook_whatsapp

        resultado = processar_webhook_whatsapp(payload, request=ctx)
        status = resultado.get("status", "?") if isinstance(resultado, dict) else "?"
        logger.info("[WebhookAsync] Processamento concluído status=%s", status)
    except Exception:
        logger.exception("[WebhookAsync] Erro no processamento em background")
    finally:
        django.db.close_old_connections()


def _despachar_em_thread(payload: Dict[str, Any], request: Any = None) -> None:
    ctx = WebhookRequestContext(request)
    thread = threading.Thread(
        target=_worker_processar,
        args=(payload, ctx),
        name=_nome_thread(payload),
        daemon=True,
    )
    thread.start()
    logger.info("[WebhookAsync] Despachado em thread %s", thread.name)


def despachar_webhook_whatsapp(data: Dict[str, Any], request: Any = None) -> None:
    """
    Enfileira no PostgreSQL (serviço webhook) ou processa em thread daemon local.
    Se a fila falhar (ex.: Postgres saturado), faz fallback para thread no web.
    """
    payload = copy.deepcopy(data)

    if webhook_usa_fila_dedicada():
        import django.db

        django.db.close_old_connections()
        try:
            from crm_app.whatsapp_webhook_fila import enfileirar_webhook

            enfileirar_webhook(payload, base_url=_base_url_de_request(request))
            logger.info("[WebhookAsync] Enfileirado telefone=%s", _nome_thread(payload))
            return
        except Exception as exc:
            logger.warning(
                "[WebhookAsync] Fila indisponível (%s) — fallback para thread local",
                exc,
            )
            django.db.close_old_connections()

    _despachar_em_thread(payload, request)


def webhook_deve_processar_assincrono() -> bool:
    if getattr(settings, "WHATSAPP_WORKER_MODE", False):
        return False
    return bool(getattr(settings, "WHATSAPP_WEBHOOK_ASYNC", True))
