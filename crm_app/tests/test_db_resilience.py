"""Testes do helper de resiliência de conexão DB."""
from __future__ import annotations

from unittest import mock

import pytest
from django.db.utils import InterfaceError, OperationalError

from crm_app.db_resilience import (
    is_db_connection_lost,
    retry_on_db_connection_error,
)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (InterfaceError("connection already closed"), True),
        (OperationalError("server closed the connection unexpectedly"), True),
        (OperationalError("SSL SYSCALL error: EOF detected"), True),
        (ValueError("outro erro"), False),
        (RuntimeError("connection already closed"), True),
    ],
)
def test_is_db_connection_lost(exc: Exception, expected: bool) -> None:
    assert is_db_connection_lost(exc) is expected


def test_retry_on_db_connection_error_succeeds_after_reconnect() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise InterfaceError("connection already closed")
        return "ok"

    with mock.patch("crm_app.db_resilience.force_close_db_connections"), mock.patch(
        "crm_app.db_resilience.close_old_connections"
    ), mock.patch("crm_app.db_resilience.time.sleep"):
        assert retry_on_db_connection_error(flaky, retries=3, delay=0) == "ok"
    assert calls["n"] == 3


def test_retry_on_db_connection_error_raises_non_connection_error() -> None:
    def boom() -> None:
        raise ValueError("falha de negocio")

    with mock.patch("crm_app.db_resilience.close_old_connections"):
        with pytest.raises(ValueError, match="falha de negocio"):
            retry_on_db_connection_error(boom, retries=3)
