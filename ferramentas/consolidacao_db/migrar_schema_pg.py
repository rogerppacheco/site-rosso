"""Copia schema public de origem para schema destino no banco central (pg_dump)."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

try:
    import psycopg2
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


def _rewrite_schema(sql: str, source_schema: str, target_schema: str) -> str:
    src = re.escape(source_schema)
    out = sql
    out = re.sub(rf"CREATE SCHEMA {src}\s*;", "", out, flags=re.IGNORECASE)
    out = re.sub(rf"COMMENT ON SCHEMA {src}\s+IS[^;]+;", "", out, flags=re.IGNORECASE)
    out = re.sub(rf"ALTER SCHEMA {src}\s+[^;]+;", "", out, flags=re.IGNORECASE)
    out = re.sub(rf"SCHEMA {src}\b", f"SCHEMA {target_schema}", out, flags=re.IGNORECASE)
    out = re.sub(rf"\b{src}\.", f"{target_schema}.", out)
    out = re.sub(rf"search_path = {src}\b", f"search_path = {target_schema}", out, flags=re.IGNORECASE)
    out = re.sub(rf"\\restrict[^\n]*\n", "", out)
    out = re.sub(rf"\\unrestrict[^\n]*\n", "", out)
    return out


def _truncate_schema(database_url: str, schema: str) -> None:
    conn = _connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT tablename FROM pg_tables WHERE schemaname = %s
                """,
                (schema,),
            )
            tables = [row[0] for row in cursor.fetchall()]
            if not tables:
                return
            quoted = ", ".join(f'"{schema}"."{name}"' for name in tables)
            cursor.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
            print(f"  TRUNCATE {len(tables)} tabelas em {schema}")
    finally:
        conn.close()


def _run_pg_dump(database_url: str, source_schema: str, data_only: bool) -> str:
    cmd = [
        "pg_dump",
        database_url,
        f"--schema={source_schema}",
        "--no-owner",
        "--no-acl",
        "--no-comments",
        "--encoding=UTF8",
    ]
    if data_only:
        cmd.append("--data-only")
        cmd.extend(["--disable-triggers"])
        cmd.extend(["--exclude-table", f"{source_schema}._prisma_migrations"])
    else:
        cmd.append("--schema-only")

    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".sql",
        delete=False,
    ) as handle:
        temp_path = handle.name

    try:
        with open(temp_path, "wb") as out_file:
            result = subprocess.run(cmd, stdout=out_file, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"pg_dump falhou: {err}")
        return Path(temp_path).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _run_psql(database_url: str, sql: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".sql",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(sql)
        temp_path = handle.name

    result = subprocess.run(
        ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-f", temp_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    Path(temp_path).unlink(missing_ok=True)
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace").strip()
        out = result.stdout.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"psql falhou: {err or out}")


def _schema_table_count(database_url: str, schema: str) -> int:
    conn = _connect(database_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                """,
                (schema,),
            )
            return int(cursor.fetchone()[0])
    finally:
        conn.close()


def _prepare_target(database_url: str, target_schema: str, force: bool) -> None:
    conn = _connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            if force:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{target_schema}" CASCADE;')
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{target_schema}";')
            cursor.execute(f'GRANT ALL ON SCHEMA "{target_schema}" TO CURRENT_USER;')
    finally:
        conn.close()


def migrar(
    source_url: str,
    target_url: str,
    source_schema: str,
    target_schema: str,
    force: bool,
    skip_schema: bool,
) -> None:
    _prepare_target(target_url, target_schema, force=force)

    if not skip_schema:
        print(f"[DDL] pg_dump schema-only {source_schema} -> {target_schema}")
        ddl = _run_pg_dump(source_url, source_schema, data_only=False)
        ddl = _rewrite_schema(ddl, source_schema, target_schema)
        _run_psql(target_url, ddl)
        tables = _schema_table_count(target_url, target_schema)
        print(f"  Tabelas criadas em {target_schema}: {tables}")

    print(f"[DADOS] pg_dump data-only {source_schema} -> {target_schema}")
    if not force:
        _truncate_schema(target_url, target_schema)
    data_sql = _run_pg_dump(source_url, source_schema, data_only=True)
    data_sql = _rewrite_schema(data_sql, source_schema, target_schema)
    wrapped = (
        "SET session_replication_role = replica;\n"
        f"{data_sql}\n"
        "SET session_replication_role = DEFAULT;\n"
    )
    _run_psql(target_url, wrapped)
    print(f"OK - dados copiados para schema {target_schema}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra schema PostgreSQL via pg_dump")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--source-schema", default="public")
    parser.add_argument("--target-schema", required=True)
    parser.add_argument("--force", action="store_true", help="DROP SCHEMA CASCADE antes")
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Pula DDL (estrutura ja criada via baseline)",
    )
    args = parser.parse_args()
    migrar(
        source_url=args.source_url,
        target_url=args.target_url,
        source_schema=args.source_schema,
        target_schema=args.target_schema,
        force=args.force,
        skip_schema=args.skip_schema,
    )


if __name__ == "__main__":
    main()
