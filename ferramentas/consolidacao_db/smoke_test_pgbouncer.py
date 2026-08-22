"""Smoke test pós-cutover PgBouncer: conexão pooled + unpooled + contagem básica."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _connect(url: str, label: str) -> None:
    conn = psycopg2.connect(url, connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0]
        print(f"  OK {label}: Postgres {version}")
    finally:
        conn.close()


def _count_schema(url: str, schema: str) -> int:
    conn = psycopg2.connect(url, connect_timeout=15)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                """,
                [schema],
            )
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pooled-url", required=True)
    parser.add_argument("--unpooled-url", required=True)
    args = parser.parse_args()

    print("=== Smoke test PgBouncer ===")
    try:
        _connect(args.pooled_url, "pooled (PgBouncer)")
        _connect(args.unpooled_url, "unpooled (Postgres direto)")
    except Exception as exc:
        print(f"  ERRO conexão: {exc}", file=sys.stderr)
        return 1

    for schema in ("public", "sysr", "syncwa"):
        try:
            n = _count_schema(args.unpooled_url, schema)
            print(f"  schema {schema}: {n} tabelas")
        except Exception as exc:
            print(f"  ERRO schema {schema}: {exc}", file=sys.stderr)
            return 1

    print("Smoke test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
