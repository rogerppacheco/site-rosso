#!/usr/bin/env python
"""Atualizar todos os contratos com status AGUARDANDO_ARRECADACAO"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, FaturaM10
from fpd_status_mapping import normalizar_status_fpd

# Buscar todos contratos com FPD = AGUARDANDO_ARRECADACAO
contratos = ContratoM10.objects.filter(
    safra='2025-12',
    status_fatura_fpd='AGUARDANDO_ARRECADACAO'
)

print(f'Total de contratos com AGUARDANDO_ARRECADACAO: {contratos.count()}')
print()

atualizados = 0
for contrato in contratos:
    status_correto = normalizar_status_fpd(contrato.status_fatura_fpd)
    count = FaturaM10.objects.filter(contrato=contrato).update(status=status_correto)
    if count > 0:
        print(f'O.S {contrato.ordem_servico}: {count} faturas → {status_correto}')
        atualizados += 1

print()
print(f'Total de contratos atualizados: {atualizados}')

# Verificação final
aguardando_restantes = FaturaM10.objects.filter(
    contrato__safra='2025-12',
    status='AGUARDANDO'
).count()
print(f'Faturas AGUARDANDO restantes: {aguardando_restantes}')
