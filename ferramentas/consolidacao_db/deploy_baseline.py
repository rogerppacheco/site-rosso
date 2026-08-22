"""Aplica DDL baseline (Prisma migrate diff) no banco central."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

_BASE = Path(__file__).resolve().parent


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


def _clean_baseline_sql(raw: str) -> str:
    raw = raw.lstrip("\ufeff")
    lines = []
    for line in raw.splitlines():
        if line.startswith("node.exe :") or line.startswith("No C:\\"):
            continue
        if line.strip().startswith("+") and "CategoryInfo" in line:
            continue
        if "RemoteException" in line or "NativeCommandError" in line:
            continue
        if line.strip() == "For more information, see: https://pris.ly/prisma-config":
            continue
        if "deprecated and will be removed in Prisma 7" in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def aplicar_baseline(database_url: str, sql_file: Path, schema: str, force: bool) -> None:
    sql = _clean_baseline_sql(sql_file.read_text(encoding="utf-8"))
    conn = _connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            if force:
                cursor.execute(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = %s
                    """,
                    (schema,),
                )
                tables = [row[0] for row in cursor.fetchall()]
                if tables:
                    cursor.execute(
                        f'DROP SCHEMA IF EXISTS "{schema}" CASCADE; '
                        f'CREATE SCHEMA "{schema}"; '
                        f'GRANT ALL ON SCHEMA "{schema}" TO CURRENT_USER;'
                    )
                    print(f"Schema {schema} recriado (force).")
            cursor.execute(sql)
        print(f"OK - baseline aplicado: {sql_file.name} -> schema {schema}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy baseline Prisma no central")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--target",
        choices=("syncwa", "sysr"),
        required=True,
        help="Qual baseline aplicar",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recria schema antes de aplicar (CASCADE)",
    )
    args = parser.parse_args()

    sql_file = _BASE / f"baseline_{args.target}.sql"
    if not sql_file.exists():
        print(f"ERRO: {sql_file} nao encontrado", file=sys.stderr)
        sys.exit(1)

    aplicar_baseline(args.database_url, sql_file, args.target, args.force)


if __name__ == "__main__":
    main()
