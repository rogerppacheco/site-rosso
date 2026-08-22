#!/usr/bin/env python
"""
VERIFICADOR E IMPORTADOR INTERATIVO
1. Verifica o que falta
2. Pergunta confirmação
3. Continua de onde parou
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
print("🔍 VERIFICADOR INTELIGENTE DE MIGRAÇÃO")
print("="*70)

def verificar_estado():
    """Analisa o que falta importar"""
    arquivos = {
        'backup_parte1_users.json': 'PARTE 1 (Usuários/Auth)',
        'backup_parte2_outros.json': 'PARTE 2 (Satélites)',
        'backup_parte3_crm.json': 'PARTE 3 (CRM)'
    }
    
    pendencias = []
    
    for arquivo, descricao in arquivos.items():
        if not os.path.exists(arquivo):
            print(f"⚠️  {arquivo} não encontrado")
            continue
        
        print(f"\n📖 Analisando {descricao}...")
        with open(arquivo, 'r', encoding='utf-8') as f:
            objects = list(serializers.deserialize("json", f.read()))
        
        # Agrupa por modelo
        por_modelo = {}
        for obj in objects:
            model_class = obj.object.__class__
            model_name = model_class.__name__
            
            if model_name not in por_modelo:
                por_modelo[model_name] = {
                    'class': model_class,
                    'total_backup': 0,
                    'ids_backup': set()
                }
            
            por_modelo[model_name]['total_backup'] += 1
            # Usa sempre o PK para contar, pois alguns modelos não possuem campo "id" (ex.: Session, CicloPagamento)
            pk_value = getattr(obj.object, 'pk', None)
            if pk_value is not None:
                por_modelo[model_name]['ids_backup'].add(pk_value)
        
        # Verifica o que existe no PostgreSQL
        arquivo_pendencias = []
        for model_name, info in por_modelo.items():
            model_class = info['class']
            # Se conseguiu capturar PKs no backup, use essa contagem para precisão; caso contrário, use total_backup bruto
            ids_backup = info['ids_backup']
            total_backup = len(ids_backup) if ids_backup else info['total_backup']
            try:
                pk_field = model_class._meta.pk.name
                ids_postgresql = set(model_class.objects.values_list(pk_field, flat=True))
                total_postgresql = len(ids_postgresql)
                
                ids_faltando = ids_backup - ids_postgresql if ids_backup else set()
                faltando = len(ids_faltando) if ids_backup else max(total_backup - total_postgresql, 0)
                
                if faltando > 0:
                    arquivo_pendencias.append({
                        'modelo': model_name,
                        'backup': total_backup,
                        'postgresql': total_postgresql,
                        'faltando': faltando,
                        'ids_faltando': sorted(list(ids_faltando))[:10],  # Primeiros 10 IDs
                        'percentual': (total_postgresql / total_backup * 100) if total_backup > 0 else 0
                    })
            except Exception as e:
                arquivo_pendencias.append({
                    'modelo': model_name,
                    'backup': total_backup,
                    'postgresql': 0,
                    'faltando': total_backup,
                    'ids_faltando': [],
                    'percentual': 0,
                    'erro': str(e)
                })
        
        if arquivo_pendencias:
            pendencias.append({
                'arquivo': arquivo,
                'descricao': descricao,
                'modelos': arquivo_pendencias
            })
    
    return pendencias

def mostrar_pendencias(pendencias):
    """Exibe relatório detalhado"""
    if not pendencias:
        print("\n✅ TODOS OS DADOS FORAM MIGRADOS COM SUCESSO!")
        return False
    
    print("\n" + "="*70)
    print("❌ DADOS PENDENTES DE MIGRAÇÃO")
    print("="*70)
    
    total_faltando = 0
    
    for arquivo_info in pendencias:
        print(f"\n📁 {arquivo_info['descricao']} ({arquivo_info['arquivo']})")
        print(f"{'Modelo':<30} {'Backup':>10} {'Atual':>10} {'Faltando':>10} {'%':>6}")
        print("-" * 70)
        
        for modelo in arquivo_info['modelos']:
            print(f"{modelo['modelo']:<30} {modelo['backup']:>10,} {modelo['postgresql']:>10,} {modelo['faltando']:>10,} {modelo['percentual']:>5.1f}%")
            
            # Mostra primeiros IDs faltando se existirem
            if modelo['ids_faltando']:
                ids_str = ', '.join(map(str, modelo['ids_faltando'][:5]))
                print(f"   └─ Faltam IDs: {ids_str}{'...' if len(modelo['ids_faltando']) > 5 else ''}")
            
            total_faltando += modelo['faltando']
    
    print(f"\n🔴 TOTAL FALTANDO: {total_faltando:,} registros")
    return True

def importar_incremental_com_progress(arquivo, nome_fase):
    """Importa apenas o que falta com barra de progresso"""
    print(f"\n🚀 Importando {nome_fase}...")
    
    with open(arquivo, 'r', encoding='utf-8') as f:
        objects = list(serializers.deserialize("json", f.read()))
    
    # Separa por modelo
    por_modelo = {}
    for obj in objects:
        model_class = obj.object.__class__
        model_name = model_class.__name__
        
        if model_name not in por_modelo:
            por_modelo[model_name] = {'class': model_class, 'objects': []}
        por_modelo[model_name]['objects'].append(obj)
    
    total_importado = 0
    
    for model_name, info in por_modelo.items():
        model_class = info['class']
        objetos = info['objects']
        
        # Pega IDs existentes (ou pk para modelos sem 'id')
        try:
            # Tenta com 'id' primeiro
            ids_existentes = set(model_class.objects.values_list('id', flat=True))
        except:
            # Se falhar, usa 'pk' (funciona para todos os modelos)
            ids_existentes = set(model_class.objects.values_list('pk', flat=True))
        
        # Filtra apenas novos
        novos = []
        for obj in objetos:
            obj_pk = obj.object.pk if hasattr(obj.object, 'pk') else None
            if obj_pk is None or obj_pk not in ids_existentes:
                novos.append(obj)
        
        if novos:
            print(f"   💾 {model_name}: {len(novos)} registros novos...")
            
            # Importa em lotes
            batch_size = 500
            for i in range(0, len(novos), batch_size):
                batch = novos[i:i + batch_size]
                try:
                    with transaction.atomic():
                        for obj in batch:
                            obj.save()
                    total_importado += len(batch)
                    print(f"      [{i+len(batch)}/{len(novos)}] ✅", end='\r')
                except Exception as e:
                    print(f"\n      ❌ Erro: {e}")
            print()  # Nova linha após progresso
    
    return total_importado

# EXECUÇÃO PRINCIPAL
if __name__ == "__main__":
    # Neutraliza signals
    def no_op(sender, **kwargs): return []
    signals.pre_save.send = no_op
    signals.post_save.send = no_op
    
    # PASSO 1: Verifica o estado
    pendencias = verificar_estado()
    tem_pendencias = mostrar_pendencias(pendencias)
    
    if not tem_pendencias:
        print("\n✨ Migração completa! Nada a fazer.")
        exit(0)
    
    # PASSO 2: Pergunta confirmação
    print("\n" + "="*70)
    resposta = input("❓ Deseja continuar a importação de onde parou? (sim/não): ").strip().lower()
    
    if resposta not in ['sim', 's', 'yes', 'y']:
        print("❌ Importação cancelada pelo usuário.")
        exit(0)
    
    # PASSO 3: Importa incrementalmente
    print("\n" + "="*70)
    print("🚀 INICIANDO IMPORTAÇÃO INCREMENTAL...")
    print("="*70)
    
    total_importado = 0
    for arquivo_info in pendencias:
        arquivo = arquivo_info['arquivo']
        descricao = arquivo_info['descricao']
        total_importado += importar_incremental_com_progress(arquivo, descricao)
    
    print("\n" + "="*70)
    print(f"✅ IMPORTAÇÃO CONCLUÍDA! {total_importado:,} registros adicionados")
    print("="*70)
    print("\n💡 Execute novamente para verificar se está 100% completo.")
