"""Registra baseline Prisma em _prisma_migrations no schema destino."""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

_BASE = Path(__file__).resolve().parent

MIGRATIONS = {
    "syncwa": {
        "repo": Path(r"C:\SyncWA"),
        "migration_name": "20260623200000_baseline_central",
        "sql_file": _BASE / "baseline_syncwa.sql",
    },
    "sysr": {
        "repo": Path(r"C:\sysr_vendas\backend"),
        "migration_name": "20260623200000_baseline_central",
        "sql_file": _BASE / "baseline_sysr.sql",
    },
}


def _connect(database_url: str):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 nao instalado")
    parsed = urlparse(database_url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        dbname=(parsed.path or "/").lstrip("/") or "postgres",
        user=parsed.username or "postgres",
        password=parsed.password or "",
    )


def registrar(database_url: str, schema: str, migration_name: str, sql_file: Path) -> None:
    sql = sql_file.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    conn = _connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{schema}"."_prisma_migrations" (
                    id VARCHAR(36) PRIMARY KEY,
                    checksum VARCHAR(64) NOT NULL,
                    finished_at TIMESTAMPTZ,
                    migration_name VARCHAR(255) NOT NULL,
                    logs TEXT,
                    rolled_back_at TIMESTAMPTZ,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    applied_steps_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                f'DELETE FROM "{schema}"."_prisma_migrations" WHERE migration_name = %s',
                (migration_name,),
            )
            cursor.execute(
                f"""
                INSERT INTO "{schema}"."_prisma_migrations"
                    (id, checksum, finished_at, migration_name, applied_steps_count)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (
                    checksum[:36],
                    checksum,
                    datetime.now(timezone.utc),
                    migration_name,
                ),
            )
        print(f"OK - _prisma_migrations registrada: {schema}.{migration_name}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Registra baseline Prisma no central")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target", choices=("syncwa", "sysr"), required=True)
    args = parser.parse_args()
    cfg = MIGRATIONS[args.target]
    registrar(
        args.database_url,
        args.target,
        cfg["migration_name"],
        cfg["sql_file"],
    )


if __name__ == "__main__":
    main()
