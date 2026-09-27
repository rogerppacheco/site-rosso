"""Cria schema nova_velox (IF NOT EXISTS). Sem DROP/CASCADE."""
from __future__ import annotations

import os
import sys

import psycopg2


def main() -> int:
    url = os.environ.get("DATABASE_UNPOOLED_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_UNPOOLED_URL/DATABASE_URL ausente", file=sys.stderr)
        return 1

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS nova_velox")
    cur.execute("GRANT USAGE ON SCHEMA nova_velox TO CURRENT_USER")
    cur.execute("GRANT CREATE ON SCHEMA nova_velox TO CURRENT_USER")
    cur.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA nova_velox GRANT ALL ON TABLES TO CURRENT_USER"
    )
    cur.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA nova_velox GRANT ALL ON SEQUENCES TO CURRENT_USER"
    )
    cur.execute(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'nova_velox'"
    )
    row = cur.fetchone()
    print("OK schema:", row[0] if row else None)
    cur.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'nova_velox'"
    )
    print("tables_in_nova_velox:", cur.fetchone()[0])
    cur.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
    )
    print("tables_in_public_untouched:", cur.fetchone()[0])
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
