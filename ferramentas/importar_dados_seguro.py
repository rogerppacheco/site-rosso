#!/usr/bin/env python
"""
Script para importar dados desabilitando signals
Evita conflitos com validações durante loaddata
"""
import os
import django
import json
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.core.serializers import deserialize
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from crm_app.models import Venda

# Desabilitar signals
print("🔇 Desabilitando signals...")
pre_save.disconnect(sender=Venda)
post_save.disconnect(sender=Venda)

backup_file = 'backup_mysql_producao_20260102_221849.json'

print(f"\n📥 Importando dados de {backup_file}...")

try:
    with open(backup_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    count = 0
    errors = []
    
    with transaction.atomic():
        for obj in deserialize('json', json.dumps(data)):
            try:
                obj.save()
                count += 1
                if count % 100 == 0:
                    print(f"✅ {count} registros importados...")
            except Exception as e:
                errors.append(f"  ❌ {obj.object.__class__.__name__} (pk={obj.object.pk}): {str(e)[:100]}")
    
    print(f"\n✅ Importação concluída!")
    print(f"📊 Total: {count} registros importados")
    
    if errors:
        print(f"\n⚠️  {len(errors)} erros encontrados:")
        for err in errors[:10]:  # Mostrar apenas os 10 primeiros
            print(err)
        if len(errors) > 10:
            print(f"  ... e mais {len(errors) - 10} erros")

except FileNotFoundError:
    print(f"❌ Arquivo {backup_file} não encontrado!")
except json.JSONDecodeError as e:
    print(f"❌ Erro ao ler JSON: {e}")
except Exception as e:
    print(f"❌ Erro durante importação: {e}")
    import traceback
    traceback.print_exc()

finally:
    # Reabilitar signals
    print("\n🔊 Reabilitando signals...")
