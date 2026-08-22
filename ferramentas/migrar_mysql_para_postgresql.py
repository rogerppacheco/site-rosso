"""
MIGRAÇÃO SEGURA: MySQL (JawsDB) → PostgreSQL (Railway)
Usa Django ORM para garantir integridade dos dados.
"""
import os
import sys
import django
from datetime import datetime

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.core.management import call_command
from django.db import connections
import json

print("=" * 70)
print("🚀 MIGRAÇÃO MYSQL → POSTGRESQL")
print("=" * 70)
print()

# 1. VERIFICAR CONEXÃO COM MYSQL ATUAL
print("✅ Etapa 1: Verificando conexão com MySQL (JawsDB)...")
try:
    connection = connections['default']
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM crm_app_cliente")
        count = cursor.fetchone()[0]
        print(f"   ✓ MySQL conectado: {count} clientes encontrados")
except Exception as e:
    print(f"   ❌ Erro ao conectar MySQL: {e}")
    sys.exit(1)

print()
print("=" * 70)
print("📋 PRÓXIMOS PASSOS:")
print("=" * 70)
print()
print("1. Copiar a DATABASE_URL do Railway PostgreSQL")
print("2. Executar o script de migração")
print()
print("⚠️  IMPORTANTE: Você terá um segundo para cancelar (Ctrl+C)")
print()

input("Pressione ENTER para continuar com a migração...")

print()
print("🔄 Etapa 2: Exportando dados do MySQL...")
print()

# 2. EXPORTAR DADOS
from django.core import serializers
from django.apps import apps

# Get all crm_app models
all_models = apps.get_models()
models_to_backup = [model for model in all_models if model._meta.app_label == 'crm_app']

total_records = 0
all_data = []

for model in models_to_backup:
    count = model.objects.count()
    if count > 0:
        print(f"   • {model._meta.verbose_name}: {count} registros")
        data = serializers.serialize('python', model.objects.all())
        all_data.extend(data)
        total_records += count

print()
print(f"✅ Total exportado: {total_records} registros")
print()

# 3. SALVAR BACKUP TEMPORÁRIO
backup_file = f"migration_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
with open(backup_file, 'w', encoding='utf-8') as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False, default=str)

print(f"💾 Backup salvo: {backup_file}")
print()

print("=" * 70)
print("✅ EXPORTAÇÃO COMPLETA!")
print("=" * 70)
print()
print("📝 PRÓXIMOS PASSOS:")
print()
print("1. Copie a DATABASE_URL do Railway PostgreSQL")
print("2. Execute: python importar_para_postgresql.py")
print("3. Cole a DATABASE_URL quando solicitado")
print()
print(f"Arquivo de dados: {backup_file}")
print()
