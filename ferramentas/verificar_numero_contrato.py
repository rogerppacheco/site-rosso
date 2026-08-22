#!/usr/bin/env python
"""
Script para verificar status do campo numero_contrato_definitivo nos ContratoM10
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD
from django.db.models import Q

print("=" * 80)
print("VERIFICAÇÃO: número_contrato_definitivo nos ContratoM10")
print("=" * 80)

# Total de contratos
total = ContratoM10.objects.count()
print(f"\n📊 Total de contratos M-10: {total}")

# Contratos com numero_contrato_definitivo preenchido
com_numero_def = ContratoM10.objects.filter(numero_contrato_definitivo__isnull=False).exclude(numero_contrato_definitivo='').count()
print(f"   ✅ Com numero_contrato_definitivo: {com_numero_def}")

# Contratos SEM numero_contrato_definitivo
sem_numero_def = total - com_numero_def
print(f"   ❌ SEM numero_contrato_definitivo: {sem_numero_def}")

if com_numero_def > 0:
    print(f"\n📝 Exemplos de contratos COM numero_contrato_definitivo:")
    exemplos = ContratoM10.objects.filter(numero_contrato_definitivo__isnull=False).exclude(numero_contrato_definitivo='')[:5]
    for c in exemplos:
        print(f"   - O.S: {c.ordem_servico} | Contrato: {c.numero_contrato} | Num Definitivo: {c.numero_contrato_definitivo}")

if sem_numero_def > 0:
    print(f"\n❌ Exemplos de contratos SEM numero_contrato_definitivo:")
    exemplos_sem = ContratoM10.objects.filter(Q(numero_contrato_definitivo__isnull=True) | Q(numero_contrato_definitivo=''))[:5]
    for c in exemplos_sem:
        print(f"   - O.S: {c.ordem_servico} | Contrato: {c.numero_contrato} | Num Definitivo: '{c.numero_contrato_definitivo}'")

# Verificar ImportacaoFPD
print(f"\n📥 ImportacaoFPD:")
total_fpd = ImportacaoFPD.objects.count()
fpd_com_contrato = ImportacaoFPD.objects.filter(contrato_m10__isnull=False).count()
fpd_sem_contrato = total_fpd - fpd_com_contrato

print(f"   Total importações FPD: {total_fpd}")
print(f"   ✅ Vinculadas a ContratoM10: {fpd_com_contrato}")
print(f"   ❌ SEM vínculo (O.S não encontrada): {fpd_sem_contrato}")

if fpd_sem_contrato > 0:
    print(f"\n   Primeiras 5 FPDs sem contrato:")
    sem_vinculos = ImportacaoFPD.objects.filter(contrato_m10__isnull=True)[:5]
    for fpd in sem_vinculos:
        print(f"      - O.S: {fpd.nr_ordem} | Fatura: {fpd.nr_fatura} | ID Contrato FPD: {fpd.id_contrato}")

print("\n" + "=" * 80)
print("ANÁLISE:")
print("=" * 80)

if sem_numero_def == 0:
    print("✅ Todos os contratos têm numero_contrato_definitivo preenchido!")
else:
    print(f"⚠️  {sem_numero_def} contratos ainda não têm numero_contrato_definitivo")
    print("\n💡 Possíveis causas:")
    print("   1. O arquivo FPD não foi importado para essas O.S")
    print("   2. A O.S do FPD não corresponde exatamente com a O.S do ContratoM10")
    print("   3. O arquivo FPD foi importado mas a coluna ID_CONTRATO estava vazia")
    
    # Verificar se tem FPD não vinculada
    if fpd_sem_contrato > 0:
        print(f"\n   ⚠️  Há {fpd_sem_contrato} registros FPD que não encontraram contrato M10!")
        print("      Verifique se as O.S estão iguais entre o arquivo de Contratos e o FPD")

print("=" * 80)
