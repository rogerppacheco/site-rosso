"""
Despacha automações PAP para fila dedicada ou thread local.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from django.conf import settings

logger = logging.getLogger(__name__)


def pap_usa_fila_dedicada() -> bool:
    return bool(
        getattr(settings, "PAP_USE_DEDICATED_WORKER", False)
        and not getattr(settings, "PAP_WORKER_MODE", False)
    )


def despachar_pap(
    tipo: str,
    telefone: str,
    payload: dict[str, Any],
    fallback: Callable[..., None],
    fallback_args: tuple[Any, ...] = (),
    *,
    prioridade: int = 5,
) -> None:
    """
    Enfileira no PostgreSQL (serviço PAP) ou executa em thread daemon (fallback).
    """
    if pap_usa_fila_dedicada():
        from crm_app.pap_job_fila import enfileirar_job_pap

        enfileirar_job_pap(tipo, payload, telefone=telefone, prioridade=prioridade)
        logger.info("[PAP_DISPATCH] Enfileirado tipo=%s telefone=%s", tipo, telefone)
        return

    thread = threading.Thread(
        target=fallback,
        args=fallback_args,
        name=f"pap-{tipo}-{telefone[-6:]}",
        daemon=True,
    )
    thread.start()
    logger.debug("[PAP_DISPATCH] Thread local tipo=%s telefone=%s", tipo, telefone)
