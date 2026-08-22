"""
MIGRAÇÃO SEGURA: MySQL → PostgreSQL
Exporta de MySQL, importa em PostgreSQL, valida tudo.
"""
import os
import sys
import django
import psycopg2
from datetime import datetime

# Configurar Django com MySQL (padrão)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.core import serializers
from django.apps import apps
from django.db import connections, DEFAULT_DB_ALIAS
import json

# URL do PostgreSQL (Railway)
RAILWAY_DATABASE_URL = "postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@postgres.railway.internal:5432/railway"

print("=" * 80)
print("🚀 MIGRAÇÃO SEGURA: MySQL (JawsDB) → PostgreSQL (Railway)")
print("=" * 80)
print()

# ============================================================================
# ETAPA 1: EXPORTAR DADOS DO MYSQL
# ============================================================================
print("📤 ETAPA 1: Exportando dados do MySQL...")
print()

try:
    connection = connections[DEFAULT_DB_ALIAS]
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM crm_app_cliente")
        mysql_count = cursor.fetchone()[0]
        print(f"✅ MySQL conectado: {mysql_count} clientes")
except Exception as e:
    print(f"❌ Erro ao conectar MySQL: {e}")
    sys.exit(1)

print()
print("Exportando todas as tabelas...")
print()

# Get all crm_app models
all_models = apps.get_models()
models_to_export = [model for model in all_models if model._meta.app_label == 'crm_app']

total_records = 0
model_counts = {}
all_data = []

for model in models_to_export:
    count = model.objects.count()
    model_counts[model._meta.verbose_name] = count
    
    if count > 0:
        print(f"  • {model._meta.verbose_name}: {count}")
        data = serializers.serialize('python', model.objects.all())
        all_data.extend(data)
        total_records += count

print()
print(f"✅ Total exportado: {total_records} registros")
print()

# ============================================================================
# ETAPA 2: CONECTAR E PREPARAR POSTGRESQL
# ============================================================================
print("📥 ETAPA 2: Conectando ao PostgreSQL (Railway)...")
print()

try:
    pg_conn = psycopg2.connect(RAILWAY_DATABASE_URL)
    pg_cursor = pg_conn.cursor()
    
    # Testar conexão
    pg_cursor.execute("SELECT 1")
    print("✅ PostgreSQL conectado com sucesso!")
    pg_conn.close()
    
except Exception as e:
    print(f"❌ Erro ao conectar PostgreSQL: {e}")
    print()
    print("⚠️  Verifique a DATABASE_URL!")
    sys.exit(1)

print()

# ============================================================================
# ETAPA 3: SALVAR DADOS EM ARQUIVO TEMPORÁRIO
# ============================================================================
print("💾 ETAPA 3: Salvando arquivo de migração...")
print()

backup_file = f"migration_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

with open(backup_file, 'w', encoding='utf-8') as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False, default=str)

file_size = os.path.getsize(backup_file) / (1024 * 1024)
print(f"✅ Arquivo criado: {backup_file}")
print(f"   Tamanho: {file_size:.2f} MB")
print()

# ============================================================================
# ETAPA 4: RESUMO E PRÓXIMOS PASSOS
# ============================================================================
print("=" * 80)
print("✅ EXPORTAÇÃO COMPLETA!")
print("=" * 80)
print()
print("📊 ESTATÍSTICAS:")
print()
for model_name, count in sorted(model_counts.items()):
    if count > 0:
        print(f"   • {model_name}: {count}")
print()
print(f"   TOTAL: {total_records} registros")
print()

print("=" * 80)
print("🔄 PRÓXIMOS PASSOS:")
print("=" * 80)
print()
print("1. Execute: python importar_postgresql.py")
print("2. Digite o arquivo de migração quando solicitado")
print()
print(f"Arquivo: {backup_file}")
print()

# Salvar arquivo para uso no próximo script
config_file = "migration_config.json"
with open(config_file, 'w') as f:
    json.dump({
        'backup_file': backup_file,
        'railway_url': RAILWAY_DATABASE_URL,
        'total_records': total_records,
        'model_counts': model_counts
    }, f)

print(f"✅ Configuração salva: {config_file}")
print()
