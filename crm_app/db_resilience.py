"""
Resiliência de conexão PostgreSQL para workers de longa duração.

Jobs Playwright podem ficar 30–60s sem tocar no banco; PgBouncer/proxy/SSL
fecham a conexão ociosa. Sem reconectar, o próximo `save()` gera
InterfaceError/OperationalError e derruba o processo.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from django.db import close_old_connections, connection, connections
from django.db.utils import InterfaceError, OperationalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CONNECTION_ERROR_MARKERS = (
    "connection already closed",
    "server closed the connection",
    "ssl syscall",
    "connection not open",
    "connection timed out",
    "could not connect",
    "terminating connection",
    "broken pipe",
    "connection reset",
)


def is_db_connection_lost(exc: BaseException) -> bool:
    """True quando a falha indica conexão Postgres/PgBouncer morta ou inacessível."""
    if isinstance(exc, (InterfaceError, OperationalError)):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _CONNECTION_ERROR_MARKERS)


def force_close_db_connections() -> None:
    """Fecha todas as conexões Django; a próxima query abre do zero."""
    close_old_connections()
    for alias in list(connections):
        try:
            connections[alias].close()
        except Exception:
            logger.debug("Falha ao fechar conexão alias=%s", alias, exc_info=True)


def ensure_fresh_db_connection() -> None:
    """Descarta conexões stale e garante uma conexão viva."""
    force_close_db_connections()
    connection.ensure_connection()


def retry_on_db_connection_error(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    delay: float = 0.4,
    label: str = "db_op",
) -> T:
    """
    Executa ``fn``; se a conexão caiu, fecha/reabre e tenta de novo.
    """
    last_exc: BaseException | None = None
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                logger.warning(
                    "[DB] Reconectando após falha de conexão (%s, tentativa %s/%s)",
                    label,
                    attempt,
                    attempts,
                )
                force_close_db_connections()
                time.sleep(delay * attempt)
            else:
                # Antes da 1ª tentativa útil após idle longo: força conexão limpa.
                close_old_connections()
            return fn()
        except Exception as exc:
            last_exc = exc
            if not is_db_connection_lost(exc) or attempt >= attempts:
                raise
            logger.warning(
                "[DB] Conexão perdida em %s: %s",
                label,
                exc,
            )
    assert last_exc is not None
    raise last_exc
