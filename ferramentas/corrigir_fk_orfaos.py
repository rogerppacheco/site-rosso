"""
CORREÇÃO DOS FKs ÓRFÃOS NA TABELA VENDA

Este script corrige referências FK inválidas em crm_venda.motivo_pendencia_id
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import Venda, MotivoPendencia

print("=" * 70)
print("CORREÇÃO DE FKs ÓRFÃOS EM VENDA")
print("=" * 70)

# Buscar todos os motivos de pendência existentes
motivos_existentes = list(MotivoPendencia.objects.all().values_list('id', flat=True))
print(f"\n✅ Motivos Pendência existentes: {motivos_existentes}")

# Buscar todas as vendas
vendas = Venda.objects.all()
print(f"\n📊 Total de vendas: {vendas.count()}")

# Verificar vendas com motivo_pendencia_id órfão
vendas_com_problema = []
for venda in vendas:
    if venda.motivo_pendencia_id and venda.motivo_pendencia_id not in motivos_existentes:
        vendas_com_problema.append(venda)
        print(f"❌ Venda {venda.id} tem motivo_pendencia_id={venda.motivo_pendencia_id} (ÓRFÃO)")

print(f"\n🔴 Total de vendas com FK órfão: {len(vendas_com_problema)}")

if not vendas_com_problema:
    print("\n✅ NENHUM PROBLEMA ENCONTRADO! Todos os FKs estão válidos.")
else:
    print("\n🔧 Corrigindo (setando para NULL)...")
    
    for venda in vendas_com_problema:
        venda.motivo_pendencia_id = None
        venda.save()
        print(f"✅ Venda {venda.id} corrigida (motivo_pendencia → NULL)")
    
    print(f"\n✅ CORREÇÃO COMPLETA! {len(vendas_com_problema)} vendas corrigidas.")

print("\n" + "=" * 70)
print("SCRIPT FINALIZADO")
print("=" * 70)
