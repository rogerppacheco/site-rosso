"""Copia _prisma_migrations do Postgres isolado sysr -> central sysr."""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

import psycopg2


def _connect(url: str):
    u = urlparse(url)
    return psycopg2.connect(
        host=u.hostname,
        port=u.port or 5432,
        dbname=u.path.lstrip("/").split("?")[0],
        user=u.username,
        password=u.password,
    )


def copiar(source_url: str, target_url: str) -> None:
    src = _connect(source_url)
    dst = _connect(target_url)
    src.autocommit = True
    dst.autocommit = True
    try:
        with src.cursor() as sc, dst.cursor() as dc:
            sc.execute(
                """
                SELECT id, checksum, finished_at, migration_name, logs,
                       rolled_back_at, started_at, applied_steps_count
                FROM public._prisma_migrations
                WHERE finished_at IS NOT NULL
                ORDER BY started_at
                """
            )
            rows = sc.fetchall()
            dc.execute('DELETE FROM sysr."_prisma_migrations"')
            for row in rows:
                dc.execute(
                    """
                    INSERT INTO sysr."_prisma_migrations"
                        (id, checksum, finished_at, migration_name, logs,
                         rolled_back_at, started_at, applied_steps_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    row,
                )
        print(f"OK - {len(rows)} migrations copiadas para sysr._prisma_migrations")
    finally:
        src.close()
        dst.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target-url", required=True)
    args = parser.parse_args()
    copiar(args.source_url, args.target_url)


if __name__ == "__main__":
    main()
