"""
TESTE RÁPIDO - VERIFICAR SE DADOS FPD ESTÃO SENDO RETORNADOS
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10

print("=" * 80)
print("TESTE: DADOS FPD NO BACKEND")
print("=" * 80)

# Pegar um contrato com dados FPD
contrato = ContratoM10.objects.filter(
    numero_contrato_definitivo__isnull=False,
    data_vencimento_fpd__isnull=False
).first()

if not contrato:
    print("\n❌ Nenhum contrato com dados FPD encontrado!")
    exit()

print(f"\n✅ ContratoM10 #{contrato.id}")
print(f"   - O.S: {contrato.ordem_servico}")
print(f"   - Número Contrato Definitivo: {contrato.numero_contrato_definitivo}")
print(f"   - Status FPD: {contrato.status_fatura_fpd}")
print(f"   - Data Vencimento: {contrato.data_vencimento_fpd}")
print(f"   - Data Pagamento: {contrato.data_pagamento_fpd}")
print(f"   - Valor Fatura: {contrato.valor_fatura_fpd}")
print(f"   - Dias Atraso: {contrato.nr_dias_atraso_fpd}")

print("\n" + "=" * 80)
print("SIMULANDO RESPOSTA DA API:")
print("=" * 80)

# Simular como seria serializado
dados_api = {
    'id': contrato.id,
    'numero_contrato': contrato.numero_contrato,
    'numero_contrato_definitivo': contrato.numero_contrato_definitivo or '-',
    'status_fatura_fpd': contrato.status_fatura_fpd or '-',
    'data_vencimento_fpd': contrato.data_vencimento_fpd.strftime('%d/%m/%Y') if contrato.data_vencimento_fpd else '-',
    'data_pagamento_fpd': contrato.data_pagamento_fpd.strftime('%d/%m/%Y') if contrato.data_pagamento_fpd else '-',
    'valor_fatura_fpd': float(contrato.valor_fatura_fpd) if contrato.valor_fatura_fpd else 0,
    'nr_dias_atraso_fpd': contrato.nr_dias_atraso_fpd or 0,
}

import json
print(json.dumps(dados_api, indent=2, ensure_ascii=False))

print("\n✅ Dados prontos para serem enviados ao frontend!")
print("=" * 80)
