"""
Migração de Dados: MySQL → PostgreSQL usando Django
Estratégia: Exportar por app e depois importar
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.core.management import call_command
from django.db import connections
import json

print("=" * 80)
print("🚀 MIGRAÇÃO DADOS: MySQL → PostgreSQL")
print("=" * 80)
print()

# Exportar apenas dados do app crm_app
print("📤 Exportando dados do app 'crm_app'...")
print()

try:
    call_command('dumpdata', 'crm_app', output='dump_crm_app.json', format='json')
    print("✅ Exportação concluída: dump_crm_app.json")
    
    # Verificar tamanho
    size = os.path.getsize('dump_crm_app.json') / (1024 * 1024)
    print(f"   Tamanho: {size:.2f} MB")
    
except Exception as e:
    print(f"❌ Erro na exportação: {e}")
    sys.exit(1)

print()

# Também exportar auth, core, etc
other_apps = ['auth', 'core', 'estoque', 'fatura_app']

for app in other_apps:
    try:
        print(f"📤 Exportando '{app}'...")
        call_command('dumpdata', app, output=f'dump_{app}.json', format='json')
        size = os.path.getsize(f'dump_{app}.json') / (1024 * 1024)
        if size > 0:
            print(f"   ✅ {size:.2f} MB")
        else:
            print(f"   ℹ️  Vazio")
            os.remove(f'dump_{app}.json')  # Remove arquivo vazio
            
    except Exception as e:
        print(f"   ⏭️  App '{app}' não encontrado ou erro: {e}")

print()
print("=" * 80)
print("✅ Exportação concluída!")
print("=" * 80)
print()
print("📝 PRÓXIMOS PASSOS:")
print()
print("1. Modificar settings.py para usar PostgreSQL")
print("2. Executar: python manage.py migrate --run-syncdb")
print("3. Executar: python manage.py loaddata dump_*.json")
print()
