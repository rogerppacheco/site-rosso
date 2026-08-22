"""
IMPORTAR BACKUP JSON PARA POSTGRESQL
Restaura dados do backup MySQL convertido para PostgreSQL
"""
import os
import sys
import json
import psycopg2
from datetime import datetime

POSTGRES_URL = "postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@maglev.proxy.rlwy.net:56422/railway"
BACKUP_FILE = "backup_mysql_producao_20260102_221849.json"

print("=" * 80)
print("📥 RESTAURAR BACKUP JSON PARA POSTGRESQL")
print("=" * 80)
print()

if not os.path.exists(BACKUP_FILE):
    print(f"❌ Arquivo {BACKUP_FILE} não encontrado!")
    sys.exit(1)

print(f"📂 Carregando backup: {BACKUP_FILE}")

try:
    with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
        backup_data = json.load(f)
    print(f"✅ {len(backup_data)} objetos carregados")
except Exception as e:
    print(f"❌ Erro ao carregar: {e}")
    sys.exit(1)

print()

# Conectar PostgreSQL
print("📡 Conectando PostgreSQL...")
try:
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cursor = pg_conn.cursor()
    pg_conn.set_session(autocommit=True)
    print("✅ PostgreSQL conectado")
except Exception as e:
    print(f"❌ Erro ao conectar: {e}")
    sys.exit(1)

print()
print("=" * 80)
print("⚠️  PRÓXIMA ETAPA")
print("=" * 80)
print()
print("Para completar a migração:")
print()
print("1. Altere gestao_equipes/settings.py para usar PostgreSQL:")
print()
print("   DATABASES = {")
print("       'default': {")
print("           'ENGINE': 'django.db.backends.postgresql',")
print("           'NAME': 'railway',")
print("           'USER': 'postgres',")
print("           'PASSWORD': 'tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz',")
print("           'HOST': 'maglev.proxy.rlwy.net',")
print("           'PORT': '56422',")
print("       }")
print("   }")
print()
print("2. Execute:")
print("   python manage.py migrate --run-syncdb")
print("   python manage.py loaddata backup_mysql_producao_20260102_221849.json")
print()
print("3. Teste localmente")
print()
print("4. Configure no Railway:")
print("   Painel Railway -> servico web -> Variables -> DATABASE_URL")
print()

pg_cursor.close()
pg_conn.close()

print("✅ Teste de conexão OK!")
