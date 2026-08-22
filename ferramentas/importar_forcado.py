#!/usr/bin/env python
"""
Importação forçada sem signals - usa save(force_insert=True)
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

# Desabilitar TODOS os signals ANTES do django.setup()
from django.db.models import signals
signals.pre_save.receivers = []
signals.post_save.receivers = []
signals.pre_delete.receivers = []
signals.post_delete.receivers = []

django.setup()

from django.core.serializers import deserialize
from django.db import transaction, connection

backup_file = 'backup_mysql_producao_20260102_221849.json'

print(f"\n📥 Importando {backup_file} SEM SIGNALS...")
print("🔇 Todos os signals foram desabilitados\n")

try:
    with open(backup_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"✅ Arquivo carregado: {len(data)} objetos\n")
    
    count = 0
    errors = []
    
    with transaction.atomic():
        for obj_data in deserialize('json', json.dumps(data)):
            try:
                # Força insert sem validações
                obj_data.object.save(force_insert=False, using='default')
                count += 1
                
                if count % 1000 == 0:
                    print(f"⏳ {count:,} registros importados...")
                    
            except Exception as e:
                error_msg = str(e)[:150]
                errors.append(f"  ❌ {obj_data.object.__class__.__name__} pk={obj_data.object.pk}: {error_msg}")
                
                # Se for erro de PK duplicada, tenta update
                if 'duplicate key' in error_msg.lower() or 'already exists' in error_msg.lower():
                    try:
                        obj_data.object.save(force_update=True, using='default')
                        count += 1
                    except:
                        pass
    
    print(f"\n✅ Importação concluída!")
    print(f"📊 Total: {count:,} registros salvos")
    
    if errors and len(errors) < 50:
        print(f"\n⚠️  {len(errors)} erros:")
        for err in errors[:20]:
            print(err)
    elif errors:
        print(f"\n⚠️  {len(errors)} erros (mostrando primeiros 20):")
        for err in errors[:20]:
            print(err)
    
    # Resetar sequences do PostgreSQL
    print("\n🔧 Resetando sequences...")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT setval(pg_get_serial_sequence('"' || table_name || '"', 'id'), 
                   COALESCE((SELECT MAX(id) FROM "' || table_name || '"), 1))
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            AND table_name NOT LIKE 'django_%' AND table_name NOT LIKE 'auth_%';
        """)
    print("✅ Sequences atualizadas!")

except FileNotFoundError:
    print(f"❌ Arquivo {backup_file} não encontrado!")
except Exception as e:
    print(f"❌ Erro: {e}")
    import traceback
    traceback.print_exc()
