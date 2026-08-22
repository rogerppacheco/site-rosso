"""Inventário de tabelas, tamanhos e contagem de linhas por schema."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None  # type: ignore[assignment]


def _parse_db_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": (parsed.path or "/").lstrip("/") or "postgres",
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


def _connect(database_url: str):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 não instalado. Use: pip install psycopg2-binary")
    params = _parse_db_url(database_url)
    return psycopg2.connect(**params)


def inventariar(database_url: str, label: str) -> dict[str, Any]:
    conn = _connect(database_url)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT current_database() AS database,
                       inet_server_addr()::text AS server_ip,
                       version() AS version
                """
            )
            meta = dict(cursor.fetchone())

            cursor.execute(
                """
                SELECT schemaname, relname AS tablename,
                       n_live_tup AS row_estimate
                FROM pg_stat_user_tables
                ORDER BY schemaname, relname
                """
            )
            tables = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                ORDER BY schema_name
                """
            )
            schemas = [row["schema_name"] for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size
                """
            )
            db_size = cursor.fetchone()["db_size"]

        by_schema: dict[str, list[dict[str, Any]]] = {}
        for row in tables:
            by_schema.setdefault(row["schemaname"], []).append(row)

        top_tables = sorted(
            tables,
            key=lambda r: int(r["row_estimate"] or 0),
            reverse=True,
        )[:15]

        return {
            "label": label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database": meta["database"],
            "server_ip": meta["server_ip"],
            "db_size": db_size,
            "schemas": schemas,
            "table_count": len(tables),
            "tables_by_schema": {
                schema: len(rows) for schema, rows in by_schema.items()
            },
            "top_tables_by_rows": top_tables,
            "tables": tables,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventário PostgreSQL")
    parser.add_argument("--label", required=True, help="Nome do banco (central, sysr, syncwa)")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="URL PostgreSQL (default: env DATABASE_URL)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[2] / "backups" / "consolidacao_db"),
        help="Diretório de saída JSON",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("ERRO: informe --database-url ou DATABASE_URL", file=sys.stderr)
        sys.exit(1)

    report = inventariar(args.database_url, args.label)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"inventario_{args.label}_{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"=== Inventário: {args.label} ===")
    print(f"Database: {report['database']} | Tamanho: {report['db_size']}")
    print(f"Schemas: {', '.join(report['schemas'])}")
    print(f"Tabelas: {report['table_count']}")
    for schema, count in sorted(report["tables_by_schema"].items()):
        print(f"  {schema}: {count} tabelas")
    print("Top 5 tabelas (linhas estimadas):")
    for row in report["top_tables_by_rows"][:5]:
        print(f"  {row['schemaname']}.{row['tablename']}: {row['row_estimate']}")
    print(f"Relatório: {out_file}")


if __name__ == "__main__":
    main()
