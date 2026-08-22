#!/usr/bin/env python
"""
Script para corrigir inconsistência de migrações no Railway:
Insere usuarios.0001_initial na tabela django_migrations com timestamp correto.

Uso (a partir da raiz do projeto):
    python scripts/migrations/fix_railway_migration.py
"""
import os
import sys
from datetime import datetime, timedelta

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from django.db import connection
from django.utils import timezone


def fix_railway_migration():
    """Insere usuarios.0001_initial na tabela django_migrations se não existir."""
    print("=" * 80)
    print("🔧 CORRIGINDO MIGRAÇÃO NO RAILWAY")
    print("=" * 80)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM django_migrations
            WHERE app = 'usuarios' AND name = '0001_initial';
        """)
        ja_existe = cursor.fetchone()[0] > 0

        if ja_existe:
            print("\n✅ Migração usuarios.0001_initial já está registrada.")
            cursor.execute("""
                SELECT applied FROM django_migrations
                WHERE app = 'admin' AND name = '0001_initial'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            admin_timestamp = result[0] if result else None
            cursor.execute("""
                SELECT applied FROM django_migrations
                WHERE app = 'usuarios' AND name = '0001_initial'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            usuarios_timestamp = result[0] if result else None
            if admin_timestamp and usuarios_timestamp and usuarios_timestamp > admin_timestamp:
                novo_timestamp = admin_timestamp - timedelta(seconds=1)
                cursor.execute("""
                    UPDATE django_migrations
                    SET applied = %s
                    WHERE app = 'usuarios' AND name = '0001_initial';
                """, [novo_timestamp])
                print(f"✅ Timestamp atualizado para: {novo_timestamp}")
            return True
        else:
            print("\n📝 Migração usuarios.0001_initial NÃO está registrada.")
            cursor.execute("""
                SELECT applied FROM django_migrations
                WHERE app = 'admin' AND name = '0001_initial'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            if result:
                usuarios_timestamp = result[0] - timedelta(seconds=1)
            else:
                usuarios_timestamp = timezone.now()
            cursor.execute("""
                INSERT INTO django_migrations (app, name, applied)
                VALUES ('usuarios', '0001_initial', %s)
                ON CONFLICT DO NOTHING;
            """, [usuarios_timestamp])
            print(f"✅ Registro inserido com timestamp: {usuarios_timestamp}")
            return True


if __name__ == "__main__":
    try:
        sucesso = fix_railway_migration()
        if sucesso:
            print("\n" + "=" * 80)
            print("✅ CORREÇÃO CONCLUÍDA!")
            print("=" * 80)
            print("\nAgora você pode executar:")
            print("  railway run python manage.py makemigrations")
            print("  railway run python manage.py migrate")
        else:
            print("\n⚠️  Nenhuma correção necessária ou problema diferente.")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
