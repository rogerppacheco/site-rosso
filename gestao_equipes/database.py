"""
Utilitários de conexão PostgreSQL com PgBouncer (modo transaction).

Railway nativo: DATABASE_URL → pooler; DATABASE_UNPOOLED_URL → Postgres direto.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_SCHEMA_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def is_pgbouncer_enabled() -> bool:
    """
    Pooler ativo somente quando runtime usa URL diferente da direta.

    DATABASE_UNPOOLED_URL sozinha (ex.: rollback Django) nao ativa modo pooler.
    """
    flag = os.environ.get("PGBOUNCER_ENABLED", "").lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    pooled = os.environ.get("DATABASE_URL", "")
    unpooled = os.environ.get("DATABASE_UNPOOLED_URL", "")
    if pooled and unpooled and pooled != unpooled:
        return True
    return False


def append_query_param(url: str, key: str, value: str) -> str:
    """Adiciona ou substitui um parâmetro de query na URL PostgreSQL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query[key] = [value]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def normalize_postgres_url(url: str) -> str:
    """Normaliza postgres:// para postgresql:// (Django/psycopg2)."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def build_django_pooled_url(url: str) -> str:
    """URL pooled para Django — conecta direto ao PgBouncer, sem ?pgbouncer=true."""
    return normalize_postgres_url(url)


def build_prisma_pooled_url(url: str) -> str:
    """URL pooled para Prisma — exige ?pgbouncer=true no query string."""
    url = normalize_postgres_url(url)
    if "pgbouncer=true" not in url:
        url = append_query_param(url, "pgbouncer", "true")
    return url


def build_pooled_url(url: str) -> str:
    """Alias Prisma (retrocompat)."""
    return build_prisma_pooled_url(url)


def build_prisma_urls(pooled_base: str, unpooled_base: str, schema: str) -> dict[str, str]:
    """Monta DATABASE_URL + DIRECT_URL para Prisma com schema dedicado."""
    pooled = append_query_param(normalize_postgres_url(pooled_base), "schema", schema)
    pooled = build_prisma_pooled_url(pooled)
    direct = append_query_param(normalize_postgres_url(unpooled_base), "schema", schema)
    return {"DATABASE_URL": pooled, "DATABASE_DIRECT_URL": direct}


def django_database_options(*, pooled: bool) -> dict[str, Any]:
    """OPTIONS do Django para Postgres com ou sem PgBouncer.

    Esta cópia (site-rosso) usa o schema rosso por padrão e nunca cai
    no public da Record, a menos que POSTGRES_SCHEMA seja definido.
    """
    _ = pooled
    opts: dict[str, Any] = {"connect_timeout": 10}
    schema = (os.environ.get("POSTGRES_SCHEMA") or "rosso").strip() or "rosso"
    if schema:
        if not _SCHEMA_NAME_RE.match(schema):
            raise ValueError(
                f"POSTGRES_SCHEMA inválido: {schema!r}. Use apenas letras, números e underscore."
            )
        opts["options"] = f"-c search_path={schema}"
    return opts
