#!/usr/bin/env python
"""
Script para debugar discrepâncias nas O.S entre ContratoM10 e ImportacaoFPD
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD

print("=" * 80)
print("DEBUG: Comparando O.S entre ContratoM10 e ImportacaoFPD")
print("=" * 80)

# Pegar alguns exemplos de cada um
contratos = ContratoM10.objects.all()[:5]
print("\n🔹 Amostra ContratoM10 (primeiros 5):")
for c in contratos:
    print(f"   - ordem_servico='{c.ordem_servico}' (len={len(c.ordem_servico) if c.ordem_servico else 0})")

fpds = ImportacaoFPD.objects.all()[:5]
print("\n🔹 Amostra ImportacaoFPD (primeiras 5):")
for f in fpds:
    print(f"   - nr_ordem='{f.nr_ordem}' (len={len(f.nr_ordem) if f.nr_ordem else 0})")

# Pegar O.S unique de cada tabela
print("\n📊 Análise de formatos:")
contratos_os = set(ContratoM10.objects.values_list('ordem_servico', flat=True).distinct()[:10])
fpds_os = set(ImportacaoFPD.objects.values_list('nr_ordem', flat=True).distinct()[:10])

print(f"\n🔹 O.S dos Contratos (amostra):")
for os in sorted(contratos_os):
    print(f"   {os}")

print(f"\n🔹 O.S do FPD (amostra):")
for os in sorted(fpds_os):
    print(f"   {os}")

# Tentar encontrar overlap
print(f"\n🔍 Procurando overlaps:")
overlap = contratos_os & fpds_os
if overlap:
    print(f"   ✅ Encontrados {len(overlap)} O.S que batem:")
    for os in overlap:
        print(f"      {os}")
else:
    print(f"   ❌ Nenhuma O.S em comum!")
    
    # Investigar o primeiro contrato vs todas as FPDs
    primeiro_contrato = ContratoM10.objects.first()
    if primeiro_contrato:
        os_contrato = primeiro_contrato.ordem_servico
        print(f"\n🔎 Procurando pela O.S do 1º contrato '{os_contrato}' no FPD...")
        
        # Buscar exatamente igual
        fpd_igual = ImportacaoFPD.objects.filter(nr_ordem=os_contrato)
        print(f"   Busca exata: {fpd_igual.count()} resultados")
        
        # Buscar sem os dois últimos dígitos (se for 8 dígitos)
        if len(os_contrato) == 8:
            os_truncado = os_contrato[:6]
            fpd_truncado = ImportacaoFPD.objects.filter(nr_ordem__startswith=os_truncado)
            print(f"   Busca iniciada com '{os_truncado}': {fpd_truncado.count()} resultados")
            if fpd_truncado.exists():
                print(f"      Exemplos: {[f.nr_ordem for f in fpd_truncado[:3]]}")

print("\n" + "=" * 80)
