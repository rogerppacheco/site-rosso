"""Testes utilitarios PgBouncer (URLs e deteccao)."""
from __future__ import annotations

import os
from unittest import mock

from gestao_equipes.database import (
    append_query_param,
    build_django_pooled_url,
    build_prisma_pooled_url,
    build_prisma_urls,
    is_pgbouncer_enabled,
)


def test_is_pgbouncer_enabled_when_urls_differ() -> None:
    env = {
        "DATABASE_URL": "postgresql://x/pooler:6432/db",
        "DATABASE_UNPOOLED_URL": "postgresql://x/postgres:5432/db",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        assert is_pgbouncer_enabled() is True


def test_is_pgbouncer_disabled_when_urls_equal() -> None:
    url = "postgresql://x/maglev:56422/railway"
    env = {
        "DATABASE_URL": url,
        "DATABASE_UNPOOLED_URL": url,
        "PGBOUNCER_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        assert is_pgbouncer_enabled() is False


def test_is_pgbouncer_disabled_by_explicit_flag() -> None:
    env = {
        "DATABASE_URL": "postgresql://x/pooler/db",
        "DATABASE_UNPOOLED_URL": "postgresql://x/direct/db",
        "PGBOUNCER_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        assert is_pgbouncer_enabled() is False


def test_build_prisma_pooled_url_adds_pgbouncer_param() -> None:
    url = "postgresql://u:p@host:5432/db"
    result = build_prisma_pooled_url(url)
    assert "pgbouncer=true" in result


def test_build_django_pooled_url_no_pgbouncer_param() -> None:
    url = "postgres://u:p@host:5432/db"
    result = build_django_pooled_url(url)
    assert result.startswith("postgresql://")
    assert "pgbouncer" not in result


def test_append_query_param_replaces_existing() -> None:
    base = "postgresql://u:p@host/db?schema=sysr"
    result = append_query_param(base, "pgbouncer", "true")
    assert result.count("schema=sysr") == 1
    assert "pgbouncer=true" in result


def test_build_prisma_urls() -> None:
    urls = build_prisma_urls(
        "postgresql://u:p@pooler/db",
        "postgresql://u:p@postgres/db",
        "sysr",
    )
    assert "schema=sysr" in urls["DATABASE_URL"]
    assert "pgbouncer=true" in urls["DATABASE_URL"]
    assert "schema=sysr" in urls["DATABASE_DIRECT_URL"]
    assert "pgbouncer" not in urls["DATABASE_DIRECT_URL"]
