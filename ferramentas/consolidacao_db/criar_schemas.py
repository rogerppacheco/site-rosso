"""Cria schemas sysr e syncwa no banco central (Fase 0)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db import connection

SQL_PATH = Path(__file__).with_name("00_criar_schemas.sql")


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(sql)
        cursor.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name IN ('sysr', 'syncwa', 'public')
            ORDER BY schema_name
            """
        )
        schemas = [row[0] for row in cursor.fetchall()]

    host = connection.settings_dict.get("HOST", "?")
    db = connection.settings_dict.get("NAME", "?")
    print(f"OK - PostgreSQL: host={host!r} db={db!r}")
    print(f"Schemas presentes: {', '.join(schemas)}")


if __name__ == "__main__":
    main()
