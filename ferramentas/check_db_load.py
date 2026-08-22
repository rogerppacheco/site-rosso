"""Diagnóstico rápido de carga no PostgreSQL de produção."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db import connection


def main() -> None:
    t0 = time.time()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        total = cursor.fetchone()[0]
        print(f"Conexoes DB ativas: {total}")

        cursor.execute(
            """
            SELECT pid, now() - query_start AS duracao, left(query, 100)
            FROM pg_stat_activity
            WHERE state = 'active'
              AND query NOT ILIKE '%pg_stat_activity%'
            ORDER BY query_start
            LIMIT 8
            """
        )
        rows = cursor.fetchall()
        print(f"Queries ativas (exceto esta): {len(rows)}")
        for pid, duracao, query in rows:
            seg = duracao.total_seconds() if duracao else 0
            print(f"  {seg:.1f}s | pid={pid} | {query}")

    print(f"Tempo da consulta: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
