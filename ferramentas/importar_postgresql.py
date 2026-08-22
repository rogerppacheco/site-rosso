"""
IMPORTAR DADOS PARA POSTGRESQL
Carrega dados do arquivo de exportação para PostgreSQL (Railway)
"""
import os
import sys
import json
import psycopg2
from datetime import datetime
from urllib.parse import urlparse

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from django.core import serializers
from django.db import connection as default_connection

# ============================================================================
# CARREGAR CONFIGURAÇÃO
# ============================================================================
print("=" * 80)
print("📥 IMPORTAR DADOS PARA POSTGRESQL (Railway)")
print("=" * 80)
print()

if not os.path.exists('migration_config.json'):
    print("❌ Arquivo migration_config.json não encontrado!")
    print("   Execute primeiro: python exportar_mysql.py")
    sys.exit(1)

with open('migration_config.json', 'r') as f:
    config = json.load(f)

backup_file = config['backup_file']
railway_url = config['railway_url']
total_records = config['total_records']
model_counts = config['model_counts']

print(f"📁 Arquivo de migração: {backup_file}")
print(f"📊 Registros para importar: {total_records}")
print()

if not os.path.exists(backup_file):
    print(f"❌ Arquivo {backup_file} não encontrado!")
    sys.exit(1)

# ============================================================================
# CONECTAR AO POSTGRESQL
# ============================================================================
print("🔗 Conectando ao PostgreSQL (Railway)...")
print()

try:
    pg_conn = psycopg2.connect(railway_url)
    pg_cursor = pg_conn.cursor()
    
    # Testar conexão
    pg_cursor.execute("SELECT 1")
    print("✅ PostgreSQL conectado!")
    
except Exception as e:
    print(f"❌ Erro ao conectar: {e}")
    sys.exit(1)

print()

# ============================================================================
# CRIAR TABELAS (MIGRAÇÕES DJANGO)
# ============================================================================
print("🏗️  Criando tabelas no PostgreSQL...")
print()

# Precisamos usar a conexão do Django para PostgreSQL
# Vamos usar um truque: executar manage.py migrate apontando para PostgreSQL

try:
    # Configurar Django para usar PostgreSQL temporariamente
    from django.conf import settings
    
    # Criar nova configuração de banco de dados PostgreSQL
    settings.DATABASES['postgresql'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'railway',
        'USER': 'postgres',
        'PASSWORD': 'tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz',
        'HOST': 'postgres.railway.internal',
        'PORT': '5432',
    }
    
    print("   Executando migrações Django...")
    
    # Apontar para o novo banco
    import django.db
    from django.core.management import call_command
    from django.db import connections
    
    # Usar alias temporário
    settings.DATABASES['default'] = settings.DATABASES['postgresql']
    
    # Recriar conexão
    connections.close_all()
    
    # Executar migrate
    call_command('migrate', '--run-syncdb', verbosity=0)
    
    print("✅ Tabelas criadas!")
    
except Exception as e:
    print(f"⚠️  Aviso ao criar tabelas: {e}")
    print("   Continuando mesmo assim...")

print()

# ============================================================================
# CARREGAR DADOS DO ARQUIVO
# ============================================================================
print("📂 Carregando dados do arquivo...")
print()

try:
    with open(backup_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"✅ Arquivo carregado: {len(data)} objetos")
    
except Exception as e:
    print(f"❌ Erro ao carregar arquivo: {e}")
    sys.exit(1)

print()

# ============================================================================
# IMPORTAR DADOS PARA POSTGRESQL
# ============================================================================
print("⚙️  Importando dados para PostgreSQL...")
print()

try:
    # Usar Django para deserializar e salvar
    from django.core.serializers import python
    
    count = 0
    errors = []
    
    for obj_data in data:
        try:
            # Usar Django para salvar o objeto
            model = obj_data['model']
            fields = obj_data['fields']
            pk = obj_data['pk']
            
            # Converter string de model para classe Django
            app_label, model_name = model.split('.')
            from django.apps import apps
            model_class = apps.get_model(app_label, model_name)
            
            # Criar instância
            instance = model_class(**fields)
            instance.pk = pk
            
            # Salvar no banco PostgreSQL (que está em settings.DATABASES['default'])
            instance.save(using='default')
            
            count += 1
            
            if count % 1000 == 0:
                print(f"   ✓ {count} registros importados...")
        
        except Exception as e:
            errors.append(f"{model}: {str(e)}")
    
    print(f"✅ Total importado: {count} registros")
    
    if errors:
        print()
        print(f"⚠️  {len(errors)} erros encontrados:")
        for err in errors[:5]:  # Mostrar apenas primeiros 5
            print(f"   • {err}")
    
except Exception as e:
    print(f"❌ Erro geral na importação: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ============================================================================
# VALIDAÇÃO
# ============================================================================
print("=" * 80)
print("✅ VALIDAÇÃO")
print("=" * 80)
print()

try:
    from django.apps import apps
    all_models = apps.get_models()
    models_to_check = [model for model in all_models if model._meta.app_label == 'crm_app']
    
    all_match = True
    for model in models_to_check:
        count = model.objects.count()
        expected = model_counts.get(model._meta.verbose_name, 0)
        
        if count == expected:
            status = "✅"
        else:
            status = "❌"
            all_match = False
        
        print(f"   {status} {model._meta.verbose_name}: {count} (esperado: {expected})")
    
    print()
    if all_match:
        print("✅ TUDO OK! Dados importados com sucesso!")
    else:
        print("⚠️  Algumas discrepâncias encontradas, mas importação completou.")
    
except Exception as e:
    print(f"❌ Erro na validação: {e}")

print()
print("=" * 80)
print("🎉 PRÓXIMO PASSO: Testar localmente com PostgreSQL")
print("=" * 80)
print()
