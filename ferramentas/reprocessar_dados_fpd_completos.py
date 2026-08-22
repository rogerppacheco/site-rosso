"""
REPROCESSAR CONTRATOS M-10 - PREENCHER DADOS FPD

Este script pega os ContratoM10 que já têm numero_contrato_definitivo
mas ainda não têm os outros dados FPD preenchidos e completa as informações.
"""

import os
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD
from django.utils import timezone

print("=" * 80)
print("REPROCESSAMENTO: PREENCHER DADOS FPD EM CONTRATOS M-10 EXISTENTES")
print("=" * 80)

# Buscar ContratoM10 que têm ordem_servico mas não têm dados FPD completos
contratos = ContratoM10.objects.filter(
    ordem_servico__isnull=False
).exclude(
    ordem_servico=''
)

print(f"\n📊 Total de ContratoM10 com O.S: {contratos.count()}")

# Contar quantos já têm dados FPD
com_dados_fpd = contratos.filter(
    numero_contrato_definitivo__isnull=False,
    data_vencimento_fpd__isnull=False
).count()

sem_dados_fpd = contratos.filter(
    numero_contrato_definitivo__isnull=True
).count() + contratos.filter(
    numero_contrato_definitivo__isnull=False,
    data_vencimento_fpd__isnull=True
).count()

print(f"✅ Com dados FPD completos: {com_dados_fpd}")
print(f"❌ Sem dados FPD ou incompletos: {sem_dados_fpd}")

if sem_dados_fpd == 0:
    print("\n✅ TODOS OS CONTRATOS JÁ ESTÃO ATUALIZADOS!")
    exit()

print("\n" + "-" * 80)
print("INICIANDO REPROCESSAMENTO...")
print("-" * 80)

atualizados = 0
nao_encontrados = 0

for contrato in contratos:
    # Pular se já tem dados FPD completos
    if contrato.numero_contrato_definitivo and contrato.data_vencimento_fpd:
        continue
    
    # Buscar FPD pela ordem_servico
    fpd = ImportacaoFPD.objects.filter(nr_ordem=contrato.ordem_servico).first()
    
    if not fpd:
        # Tentar campo alternativo
        fpd = ImportacaoFPD.objects.filter(numero_os=contrato.ordem_servico).first()
    
    if fpd and fpd.id_contrato:
        # Atualizar todos os campos
        contrato.numero_contrato_definitivo = fpd.id_contrato
        contrato.data_vencimento_fpd = fpd.dt_venc_orig
        contrato.data_pagamento_fpd = fpd.dt_pagamento
        contrato.status_fatura_fpd = fpd.ds_status_fatura
        contrato.valor_fatura_fpd = fpd.vl_fatura
        contrato.nr_dias_atraso_fpd = fpd.nr_dias_atraso
        contrato.data_ultima_sincronizacao_fpd = timezone.now()
        contrato.save()
        
        # Vincular FPD ao contrato se ainda não estiver
        if not fpd.contrato_m10:
            fpd.contrato_m10 = contrato
            fpd.save()
        
        atualizados += 1
        print(f"✅ ContratoM10 #{contrato.id} - O.S {contrato.ordem_servico}")
        print(f"   → Contrato: {fpd.id_contrato}")
        print(f"   → Status: {fpd.ds_status_fatura}")
        print(f"   → Vencimento: {fpd.dt_venc_orig}")
        print(f"   → Pagamento: {fpd.dt_pagamento or 'N/A'}")
        print(f"   → Valor: R$ {fpd.vl_fatura}")
        print()
    else:
        nao_encontrados += 1

print("\n" + "=" * 80)
print("RESULTADO FINAL")
print("=" * 80)
print(f"✅ Atualizados: {atualizados}")
print(f"❌ Não encontrados no FPD: {nao_encontrados}")
print(f"📊 Taxa de sucesso: {(atualizados / (atualizados + nao_encontrados) * 100):.1f}%")
print("=" * 80)
