#!/usr/bin/env python
"""
Procurar O.S do Contrato M10 na ImportacaoFPD com diferentes estratégias
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD

print("=" * 80)
print("INVESTIGAÇÃO: Buscando O.S de ContratoM10 no FPD")
print("=" * 80)

# Pegar alguns contratos na faixa de overlap
contratos_overlap = ContratoM10.objects.filter(
    ordem_servico__gte='07800000',
    ordem_servico__lte='07829629'
).values_list('ordem_servico', flat=True).distinct()

print(f"\n🔹 Contratos M10 na faixa de overlap (07800000-07829629): {len(list(contratos_overlap))}")

# Para cada um, buscar no FPD
encontrados = 0
nao_encontrados = 0

for i, os_contrato in enumerate(list(contratos_overlap)[:20]):
    fpd = ImportacaoFPD.objects.filter(nr_ordem=os_contrato).first()
    if fpd:
        print(f"   ✅ {os_contrato}: ENCONTRADO no FPD")
        print(f"      ID Contrato: {fpd.id_contrato} | Fatura: {fpd.nr_fatura}")
        encontrados += 1
    else:
        print(f"   ❌ {os_contrato}: NÃO ENCONTRADO no FPD")
        nao_encontrados += 1

print(f"\n📊 Resultados:")
print(f"   ✅ Encontrados: {encontrados}")
print(f"   ❌ Não encontrados: {nao_encontrados}")

if encontrados == 0:
    print(f"\n💡 Nenhuma correspondência encontrada mesmo na faixa de overlap!")
    print(f"   Possíveis causas:")
    print(f"   1. O arquivo FPD foi importado ANTES do arquivo de Contratos M10")
    print(f"   2. O arquivo FPD tem um formato diferente de O.S (formatação diferente)")
    
    # Verificar timestamp
    from django.db.models import Min
    primeiro_contrato = ContratoM10.objects.order_by('criado_em').first()
    primeira_fpd = ImportacaoFPD.objects.order_by('criado_em').first()
    
    if primeiro_contrato and primeira_fpd:
        print(f"\n🕐 Timeline:")
        print(f"   Primeiro ContratoM10: {primeiro_contrato.criado_em}")
        print(f"   Primeiro ImportacaoFPD: {primeira_fpd.criado_em}")
        
        if primeira_fpd.criado_em < primeiro_contrato.criado_em:
            print(f"   ⚠️  FPD foi importado ANTES dos Contratos!")
            print(f"   ⚠️  Por isso a importação FPD não encontrou os contratos")

print("\n" + "=" * 80)
