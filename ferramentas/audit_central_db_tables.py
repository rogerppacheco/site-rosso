"""Lista tabelas e tipos do PostgreSQL central (produção)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db import connection

SYSR_TABLES = {
    "users", "pipeline_stages", "operators", "plans", "leads", "deals",
    "deal_audit_calls", "conversations", "messages", "audit_logs",
    "whatsapp_instances", "viabilities", "system_statuses", "reason_codes",
    "_prisma_migrations",
}

SYNCWA_TABLES = {
    "User", "Plan", "Subscription", "UsageMonthly", "Instance", "MessageLog",
}


def main() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY schemaname, tablename
            """
        )
        rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT n.nspname, t.typname
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public' AND t.typtype = 'e'
            ORDER BY t.typname
            """
        )
        enums = [r[1] for r in cursor.fetchall()]

    tables = [t for _, t in rows]
    table_set = set(tables)

    print(f"Total tabelas: {len(tables)}")
    print(f"Total enums public: {len(enums)}")
    print()
    print("=== Conflitos sysr-vendas (tabelas que JÁ existem no banco central) ===")
    for t in sorted(SYSR_TABLES):
        status = "EXISTE" if t in table_set else "livre"
        print(f"  {t:30} {status}")

    print()
    print("=== Conflitos SyncWA (tabelas que JÁ existem no banco central) ===")
    for t in sorted(SYNCWA_TABLES):
        status = "EXISTE" if t in table_set else "livre"
        print(f"  {t:30} {status}")

    print()
    print("=== Tabelas centrais com nomes genericos (amostra) ===")
    keywords = ("user", "plan", "message", "instance", "subscription", "lead", "deal")
    for t in sorted(tables):
        tl = t.lower()
        if any(k in tl for k in keywords):
            print(f"  {t}")

    print()
    print("=== Enums public (amostra, max 40) ===")
    for e in enums[:40]:
        print(f"  {e}")
    if len(enums) > 40:
        print(f"  ... +{len(enums)-40} enums")


if __name__ == "__main__":
    main()
