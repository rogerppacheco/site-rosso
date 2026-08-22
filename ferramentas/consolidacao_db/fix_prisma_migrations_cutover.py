"""Corrige _prisma_migrations apos cutover (marca migrations como aplicadas)."""
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

SYNCWA_MIGRATIONS_DIR = Path(r"C:\SyncWA\prisma\migrations")


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


def _ensure_table(cursor, schema: str) -> None:
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


def _checksum(sql_path: Path) -> str:
    return hashlib.sha256(sql_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def fix_syncwa(database_url: str) -> None:
    migrations = sorted(
        path for path in SYNCWA_MIGRATIONS_DIR.iterdir()
        if path.is_dir() and (path / "migration.sql").exists()
    )
    conn = _connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            _ensure_table(cursor, "syncwa")
            cursor.execute('DELETE FROM syncwa."_prisma_migrations"')
            now = datetime.now(timezone.utc)
            for path in migrations:
                name = path.name
                checksum = _checksum(path / "migration.sql")
                cursor.execute(
                    """
                    INSERT INTO syncwa."_prisma_migrations"
                        (id, checksum, finished_at, migration_name, applied_steps_count, started_at)
                    VALUES (%s, %s, %s, %s, 1, %s)
                    """,
                    (checksum[:36], checksum, now, name, now),
                )
                print(f"  syncwa: {name}")
        print(f"OK - {len(migrations)} migrations marcadas em syncwa")
    finally:
        conn.close()


def fix_evolution(database_url: str) -> None:
    """Remove registros falhos; mantem historico existente do dump sysr."""
    conn = _connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            _ensure_table(cursor, "sysr")
            cursor.execute(
                """
                DELETE FROM sysr."_prisma_migrations"
                WHERE finished_at IS NULL OR rolled_back_at IS NOT NULL
                """
            )
            deleted = cursor.rowcount
            cursor.execute(
                """
                UPDATE sysr."_prisma_migrations"
                SET finished_at = COALESCE(finished_at, started_at, now()),
                    applied_steps_count = GREATEST(applied_steps_count, 1)
                WHERE finished_at IS NULL
                """
            )
        print(f"OK - evolution/sysr: removidos {deleted} registros falhos")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix Prisma migrations pos-cutover")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target", choices=("syncwa", "evolution", "all"), default="all")
    args = parser.parse_args()

    if args.target in ("syncwa", "all"):
        fix_syncwa(args.database_url)
    if args.target in ("evolution", "all"):
        fix_evolution(args.database_url)


if __name__ == "__main__":
    main()
