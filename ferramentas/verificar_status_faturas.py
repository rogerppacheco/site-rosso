#!/usr/bin/env python
"""Verificar status das faturas na safra 2025-12"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, FaturaM10

print('=== Verificando contratos da safra 2025-12 ===')
total_contratos = ContratoM10.objects.filter(safra='2025-12').count()
print(f'Total de contratos na safra: {total_contratos}')
print()

print('=== Faturas por status ===')
total_faturas = FaturaM10.objects.filter(contrato__safra='2025-12').count()
print(f'Total de faturas: {total_faturas}')
pago = FaturaM10.objects.filter(contrato__safra='2025-12', status='PAGO').count()
nao_pago = FaturaM10.objects.filter(contrato__safra='2025-12', status='NAO_PAGO').count()
aguardando = FaturaM10.objects.filter(contrato__safra='2025-12', status='AGUARDANDO').count()
atrasado = FaturaM10.objects.filter(contrato__safra='2025-12', status='ATRASADO').count()
outros = FaturaM10.objects.filter(contrato__safra='2025-12', status='OUTROS').count()
print(f'PAGO: {pago}')
print(f'NAO_PAGO: {nao_pago}')
print(f'AGUARDANDO: {aguardando}')
print(f'ATRASADO: {atrasado}')
print(f'OUTROS: {outros}')
print()

print('=== Verificando contrato 07532883 ===')
c = ContratoM10.objects.filter(ordem_servico='07532883').first()
if c:
    faturas = FaturaM10.objects.filter(contrato=c)
    print(f'O.S: {c.ordem_servico}')
    print(f'Status FPD do contrato: {c.status_fatura_fpd}')
    print(f'Total faturas: {faturas.count()}')
    for s in ['PAGO', 'NAO_PAGO', 'AGUARDANDO', 'ATRASADO', 'OUTROS']:
        count = faturas.filter(status=s).count()
        if count > 0:
            print(f'  {s}: {count}')
else:
    print('Contrato não encontrado')
print()

print('=== Contratos com faturas AGUARDANDO ===')
contratos_aguard = ContratoM10.objects.filter(
    safra='2025-12', 
    faturas__status='AGUARDANDO'
).distinct()
print(f'Total: {contratos_aguard.count()} contratos')
for c in contratos_aguard[:10]:
    count_aguard = FaturaM10.objects.filter(contrato=c, status='AGUARDANDO').count()
    print(f'O.S: {c.ordem_servico}, FPD: {c.status_fatura_fpd}, Faturas AGUARDANDO: {count_aguard}')
