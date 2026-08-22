#!/usr/bin/env python
"""
Script para verificar se a tabela RecordApoia existe no banco.

Uso (a partir da raiz do projeto):
    python scripts/migrations/check_recordapoia_table.py
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from django.db import connection


def check_table_exists():
    """Verifica se a tabela crm_app_recordapoia existe."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'crm_app_recordapoia'
            );
        """)
        exists = cursor.fetchone()[0]

        if exists:
            print("✅ Tabela crm_app_recordapoia EXISTE no banco")
            cursor.execute("SELECT COUNT(*) FROM crm_app_recordapoia")
            count = cursor.fetchone()[0]
            print(f"   Total de registros: {count}")
        else:
            print("❌ Tabela crm_app_recordapoia NÃO EXISTE no banco")
            print("   A migração foi marcada como FAKED, mas a tabela não foi criada.")
            print("\n💡 Solução:")
            print("   1. Desmarcar a migração 0071 como fake:")
            print("      railway run python manage.py migrate crm_app 0070 --fake")
            print("   2. Aplicar a migração 0071 de verdade:")
            print("      railway run python manage.py migrate crm_app 0071")
        return exists


if __name__ == "__main__":
    try:
        check_table_exists()
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
