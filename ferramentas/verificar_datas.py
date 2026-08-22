#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ImportacaoFPD, FaturaM10

print("\n" + "="*80)
print("✅ VERIFICAÇÃO FINAL - DATAS CORRIGIDAS")
print("="*80 + "\n")

# 1. Verificar ImportacaoFPD
print("📊 ImportacaoFPD - Amostra com datas:")
print("-" * 80)
registros_fpd = ImportacaoFPD.objects.filter(contrato_m10__isnull=False)[:5]
for reg in registros_fpd:
    print(f"O.S: {reg.nr_ordem} | Vencimento: {reg.dt_venc_orig} | Pagamento: {reg.dt_pagamento} | Status: {reg.ds_status_fatura}")

# 2. Verificar FaturaM10 (fatura 1)
print("\n📊 FaturaM10 (Fatura 1) - Amostra com datas:")
print("-" * 80)
faturas = FaturaM10.objects.filter(numero_fatura=1, contrato__ordem_servico__isnull=False)[:10]
for fatura in faturas:
    print(f"O.S: {fatura.contrato.ordem_servico} | Vencimento: {fatura.data_vencimento} | Pagamento: {fatura.data_pagamento} | Status: {fatura.status}")

# 3. Verificar se as datas estão corretas (não em 1970)
print("\n🔍 ANÁLISE DE DATAS:")
print("-" * 80)
from datetime import date

datas_1970 = FaturaM10.objects.filter(numero_fatura=1, data_vencimento=date(1970, 1, 1)).count()
datas_validas = FaturaM10.objects.filter(numero_fatura=1, data_vencimento__gt=date(2020, 1, 1)).count()

print(f"FaturaM10 com vencimento em 1970-01-01: {datas_1970}")
print(f"FaturaM10 com vencimento após 2020: {datas_validas}")
print(f"Total FaturaM10 (fatura 1): {FaturaM10.objects.filter(numero_fatura=1).count()}")

if datas_1970 == 0 and datas_validas > 0:
    print(f"\n🎉 SUCESSO! Datas convertidas corretamente!")
else:
    print(f"\n⚠️  Atenção: Ainda há problemas com as datas")

print("\n" + "="*80)
