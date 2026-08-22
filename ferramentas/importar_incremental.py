#!/usr/bin/env python
"""
IMPORTADOR INCREMENTAL
Continua de onde parou, importa apenas o que falta
"""
import os
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.core import serializers
from django.db import transaction
from django.db.models import signals
from django.apps import apps

print("="*70)
print("🔄 IMPORTADOR INCREMENTAL (Continua de onde parou)")
print("="*70)

def lobotomizar_signals():
    print("🔇 Neutralizando signals...")
    def no_op(sender, **kwargs): return []
    signals.pre_save.send = no_op
    signals.post_save.send = no_op
    signals.m2m_changed.send = no_op
    signals.pre_delete.send = no_op
    signals.post_delete.send = no_op

def importar_incremental(arquivo, nome_fase):
    """Importa apenas registros que NÃO existem no banco"""
    print(f"\n📥 [{nome_fase}] Importando apenas o que falta de {arquivo}...")
    
    if not os.path.exists(arquivo):
        print(f"❌ Arquivo não encontrado")
        return
    
    with open(arquivo, 'r', encoding='utf-8') as f:
        objects = list(serializers.deserialize("json", f.read()))
    
    print(f"📊 Total no backup: {len(objects)} registros")
    
    # Separa por modelo para otimizar
    por_modelo = {}
    for obj in objects:
        model_class = obj.object.__class__
        model_key = f"{model_class._meta.app_label}.{model_class.__name__}"
        
        if model_key not in por_modelo:
            por_modelo[model_key] = []
        por_modelo[model_key].append(obj)
    
    total_importado = 0
    total_ignorado = 0
    
    for model_key, objetos in por_modelo.items():
        model_class = objetos[0].object.__class__
        model_name = model_class.__name__
        
        print(f"\n🔍 Verificando {model_name}...")
        
        # Pega IDs que já existem no banco
        try:
            ids_existentes = set(model_class.objects.values_list('id', flat=True))
        except:
            ids_existentes = set()
        
        novos = []
        for obj in objetos:
            obj_id = obj.object.id if hasattr(obj.object, 'id') else None
            
            if obj_id is None or obj_id not in ids_existentes:
                novos.append(obj)
            else:
                total_ignorado += 1
        
        if novos:
            print(f"   💾 Importando {len(novos)} novos registros de {model_name}...")
            
            # Importa em lotes de 500
            batch_size = 500
            for i in range(0, len(novos), batch_size):
                batch = novos[i:i + batch_size]
                
                try:
                    with transaction.atomic():
                        for obj in batch:
                            obj.save()
                    total_importado += len(batch)
                    print(f"      ✅ Lote {i//batch_size + 1}: {len(batch)} registros salvos")
                except Exception as e:
                    print(f"      ❌ Erro no lote {i//batch_size + 1}: {e}")
        else:
            print(f"   ✅ {model_name}: Todos os registros já existem")
    
    print(f"\n📊 Resumo {nome_fase}:")
    print(f"   ✅ Importados: {total_importado}")
    print(f"   ⏭️  Ignorados (já existiam): {total_ignorado}")

if __name__ == "__main__":
    lobotomizar_signals()
    
    # Importa cada arquivo incrementalmente
    print("\n🚀 INICIANDO IMPORTAÇÃO INCREMENTAL...")
    
    importar_incremental('backup_parte1_users.json', 'FASE 1')
    importar_incremental('backup_parte2_outros.json', 'FASE 2')
    importar_incremental('backup_parte3_crm.json', 'FASE 3 (CRM - Continuando)')
    
    print("\n✅ IMPORTAÇÃO INCREMENTAL CONCLUÍDA!")
    print("\n💡 Execute 'python comparar_backup_postgresql.py' para verificar se está completo")
