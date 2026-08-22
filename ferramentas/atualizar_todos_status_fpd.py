#!/usr/bin/env python
"""
Atualizar TODAS as faturas com base no status_fatura_fpd do contrato
Aplica o novo mapeamento correto
"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, FaturaM10
from fpd_status_mapping import normalizar_status_fpd

print('=== Atualizando TODAS as faturas da safra 2025-12 com novo mapeamento ===\n')

# Buscar TODOS os contratos da safra que têm status FPD definido
contratos = ContratoM10.objects.filter(
    safra='2025-12',
    status_fatura_fpd__isnull=False
).exclude(status_fatura_fpd='')

print(f'Total de contratos com status FPD: {contratos.count()}\n')

atualizados = 0
ja_corretos = 0
sem_faturas = 0

for contrato in contratos:
    # Normalizar o status do contrato usando o novo mapeamento
    status_correto = normalizar_status_fpd(contrato.status_fatura_fpd)
    
    # Buscar todas as faturas do contrato
    faturas = FaturaM10.objects.filter(contrato=contrato)
    
    if not faturas.exists():
        sem_faturas += 1
        continue
    
    # Atualizar todas as faturas que estão com status diferente
    faturas_erradas = faturas.exclude(status=status_correto)
    
    if faturas_erradas.exists():
        count = faturas_erradas.count()
        faturas_erradas.update(status=status_correto)
        print(f'O.S {contrato.ordem_servico}: {count} faturas atualizadas para {status_correto} (FPD: {contrato.status_fatura_fpd})')
        atualizados += 1
    else:
        ja_corretos += 1

print(f'\n{'='*60}')
print(f'RESUMO:')
print(f'  ✓ Contratos já corretos: {ja_corretos}')
print(f'  ↻ Contratos atualizados: {atualizados}')
print(f'  ⚠ Sem faturas: {sem_faturas}')
print(f'{'='*60}')

# Verificação final
print(f'\nVerificação final:')
pago = FaturaM10.objects.filter(contrato__safra='2025-12', status='PAGO').count()
nao_pago = FaturaM10.objects.filter(contrato__safra='2025-12', status='NAO_PAGO').count()
aguardando = FaturaM10.objects.filter(contrato__safra='2025-12', status='AGUARDANDO').count()
print(f'  PAGO: {pago}')
print(f'  NAO_PAGO: {nao_pago}')
print(f'  AGUARDANDO: {aguardando}')
