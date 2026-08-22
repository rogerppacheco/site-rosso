"""Smoke test Fase 1: compara contagens origem vs destino."""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None  # type: ignore[assignment]


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


def _list_tables(database_url: str, schema: str) -> list[str]:
    conn = _connect(database_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = %s ORDER BY tablename
                """,
                (schema,),
            )
            return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def _exact_count(database_url: str, schema: str, table: str) -> int:
    conn = _connect(database_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            return int(cursor.fetchone()[0])
    finally:
        conn.close()


def comparar(
    source_url: str,
    target_url: str,
    source_schema: str,
    target_schema: str,
    exact_all: bool,
    skip_tables: set[str],
) -> int:
    src_tables = _list_tables(source_url, source_schema)
    dst_tables = _list_tables(target_url, target_schema)
    errors = 0

    print(f"=== Smoke test: {source_schema} -> {target_schema} ===")
    print(f"Tabelas origem: {len(src_tables)} | destino: {len(dst_tables)}")

    missing = sorted(set(src_tables) - set(dst_tables) - skip_tables)
    if missing:
        errors += len(missing)
        print(f"FALTANDO no destino ({len(missing)}): {', '.join(missing[:10])}")

    for table in sorted(set(src_tables) & set(dst_tables) - skip_tables):
        if exact_all:
            s_count = _exact_count(source_url, source_schema, table)
            d_count = _exact_count(target_url, target_schema, table)
        else:
            s_count = _exact_count(source_url, source_schema, table)
            d_count = _exact_count(target_url, target_schema, table)

        if s_count != d_count:
            errors += 1
            print(f"  DIVERGENTE {table}: origem={s_count} destino={d_count}")
        elif s_count > 0:
            print(f"  OK {table}: {d_count}")

    if errors == 0:
        print("RESULTADO: OK")
    else:
        print(f"RESULTADO: {errors} problema(s)")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test consolidacao Fase 1")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--source-schema", default="public")
    parser.add_argument("--target-schema", required=True)
    parser.add_argument(
        "--skip",
        nargs="*",
        default=["_prisma_migrations"],
        help="Tabelas ignoradas na comparacao",
    )
    args = parser.parse_args()
    code = comparar(
        args.source_url,
        args.target_url,
        args.source_schema,
        args.target_schema,
        exact_all=True,
        skip_tables=set(args.skip),
    )
    sys.exit(1 if code else 0)


if __name__ == "__main__":
    main()
