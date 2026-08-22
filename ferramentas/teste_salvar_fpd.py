"""
Teste simples para verificar se ImportacaoFPD está salvando
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10
from django.utils import timezone
from decimal import Decimal

print("🧪 TESTE: Salvar registro em ImportacaoFPD")
print("=" * 80)

# Pegar um contrato M10 existente
contrato = ContratoM10.objects.first()

if not contrato:
    print("❌ Nenhum ContratoM10 no banco!")
    exit(1)

print(f"✅ ContratoM10 encontrado: {contrato.ordem_servico} - {contrato.cliente_nome}")

# Tentar salvar um registro FPD
print("\n📝 Tentando salvar ImportacaoFPD...")

try:
    importacao_fpd, criado = ImportacaoFPD.objects.update_or_create(
        nr_ordem='TESTE_DEBUG_001',
        nr_fatura='FAT_DEBUG_001',
        defaults={
            'id_contrato': 'ID_TEST',
            'dt_venc_orig': timezone.now().date(),
            'dt_pagamento': None,
            'nr_dias_atraso': 0,
            'ds_status_fatura': 'ABERTO',
            'vl_fatura': Decimal('100.00'),
            'contrato_m10': contrato,
        }
    )
    
    if criado:
        print(f"✅ Registro CRIADO com sucesso!")
    else:
        print(f"✅ Registro ATUALIZADO com sucesso!")
    
    print(f"   ID: {importacao_fpd.id}")
    print(f"   O.S: {importacao_fpd.nr_ordem}")
    print(f"   Fatura: {importacao_fpd.nr_fatura}")
    print(f"   Valor: R$ {importacao_fpd.vl_fatura}")
    print(f"   ContratoM10: {importacao_fpd.contrato_m10.id if importacao_fpd.contrato_m10 else 'Nenhum'}")
    
except Exception as e:
    print(f"❌ ERRO ao salvar: {str(e)}")
    import traceback
    traceback.print_exc()

# Verificar se está no banco
print("\n📊 Verificando no banco...")
total = ImportacaoFPD.objects.count()
print(f"   Total de registros: {total}")

# Buscar o registro que acabamos de criar
registro = ImportacaoFPD.objects.filter(nr_ordem='TESTE_DEBUG_001').first()
if registro:
    print(f"   ✅ Registro encontrado no banco (ID: {registro.id})")
else:
    print(f"   ❌ Registro NÃO encontrado no banco!")

print("\n" + "=" * 80)
print("✅ Teste concluído!")
