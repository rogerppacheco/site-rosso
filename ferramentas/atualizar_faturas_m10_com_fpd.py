#!/usr/bin/env python
"""
Script para atualizar FaturaM10 (fatura 1) com dados de vencimento e pagamento do FPD
O FPD é apenas da fatura 1, então atualizamos numero_fatura=1
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ImportacaoFPD, FaturaM10, ContratoM10
from django.utils import timezone
from decimal import Decimal

print("\n" + "="*80)
print("🔄 ATUALIZAÇÃO DA FATURA 1 COM DADOS DO FPD")
print("="*80 + "\n")

# Buscar todos os registros da ImportacaoFPD que têm vínculo M10
registros_fpd = ImportacaoFPD.objects.filter(contrato_m10__isnull=False).select_related('contrato_m10')

print(f"📊 Registros FPD com vínculo M10: {registros_fpd.count()}")

atualizados = 0
criados = 0
erros = []

for idx, fpd in enumerate(registros_fpd, 1):
    try:
        contrato = fpd.contrato_m10
        
        # Buscar ou criar FaturaM10 para fatura 1 (única que o FPD atualiza)
        fatura, criado = FaturaM10.objects.update_or_create(
            contrato=contrato,
            numero_fatura=1,  # FPD é apenas da fatura 1
            defaults={
                'numero_fatura_operadora': fpd.nr_fatura,  # NR_FATURA do arquivo FPD
                'data_vencimento': fpd.dt_venc_orig,
                'data_pagamento': fpd.dt_pagamento,
                'dias_atraso': fpd.nr_dias_atraso,
                'status': fpd.ds_status_fatura,
                
                # Campos FPD para rastreabilidade
                'id_contrato_fpd': fpd.id_contrato,
                'dt_pagamento_fpd': fpd.dt_pagamento,
                'ds_status_fatura_fpd': fpd.ds_status_fatura,
                'data_importacao_fpd': timezone.now(),
                
                # Valor da fatura
                'valor': fpd.vl_fatura,
            }
        )
        
        if criado:
            criados += 1
            if idx <= 5:
                print(f"✅ CRIADO - FaturaM10 (Fatura 1) | O.S: {contrato.ordem_servico} | "
                      f"Vencimento: {fpd.dt_venc_orig} | Status: {fpd.ds_status_fatura}")
        else:
            atualizados += 1
            if idx <= 5:
                print(f"🔄 ATUALIZADO - FaturaM10 (Fatura 1) | O.S: {contrato.ordem_servico} | "
                      f"Vencimento: {fpd.dt_venc_orig} | Status: {fpd.ds_status_fatura}")
        
        if idx % 100 == 0:
            print(f"⏳ Processados {idx}/{registros_fpd.count()} registros...")
            
    except Exception as e:
        erros.append(f"O.S {fpd.contrato_m10.ordem_servico}: {str(e)}")
        if len(erros) <= 10:
            print(f"❌ ERRO - {str(e)}")

print("\n" + "="*80)
print("✅ PROCESSAMENTO CONCLUÍDO")
print("="*80 + "\n")

print(f"📊 RESULTADOS:")
print(f"   Total processados: {registros_fpd.count()}")
print(f"   FaturaM10 (Fatura 1) CRIADAS: {criados}")
print(f"   FaturaM10 (Fatura 1) ATUALIZADAS: {atualizados}")
print(f"   Erros: {len(erros)}")

if erros:
    print(f"\n❌ ERROS ENCONTRADOS:")
    for erro in erros[:10]:
        print(f"   {erro}")

print("\n" + "="*80)
print("📈 AMOSTRA DE DADOS ATUALIZADOS:")
print("="*80 + "\n")

# Mostrar amostra de FaturaM10 (fatura 1) atualizadas
faturas_atualizadas = FaturaM10.objects.filter(
    numero_fatura=1,
    ds_status_fatura_fpd__isnull=False
).select_related('contrato')[:10]

print(f"Amostra de FaturaM10 (Fatura 1) com dados FPD:\n")

for fatura in faturas_atualizadas:
    print(f"📋 Contrato: {fatura.contrato.numero_contrato} ({fatura.contrato.cliente_nome})")
    print(f"   O.S: {fatura.contrato.ordem_servico}")
    print(f"   NR_FATURA FPD: {fatura.numero_fatura_operadora}")
    print(f"   ID_CONTRATO FPD: {fatura.id_contrato_fpd}")
    print(f"   Vencimento: {fatura.data_vencimento}")
    print(f"   Pagamento: {fatura.data_pagamento}")
    print(f"   Status: {fatura.status}")
    print(f"   Dias Atraso: {fatura.dias_atraso}")
    print(f"   Valor: R$ {fatura.valor:,.2f}")
    print()

print("="*80)
