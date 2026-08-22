#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ImportacaoFPD

print("\n" + "="*80)
print("VERIFICAÇÃO DE LEADING ZEROS NO ID_CONTRATO")
print("="*80 + "\n")

# Ver alguns registros recém-criados (id > 10300)
registros = ImportacaoFPD.objects.filter(id__gte=10300, id__lte=10310)
print(f"Total encontrados: {registros.count()}\n")

for reg in registros:
    print(f"ID: {reg.id:5d} | O.S: {reg.nr_ordem} | ID_CONTRATO: '{reg.id_contrato}' | FATURA: {reg.nr_fatura}")

# Também verificar alguns que têm match M10
print("\n" + "="*80)
print("REGISTROS COM MATCH M10:")
print("="*80 + "\n")
registros_m10 = ImportacaoFPD.objects.filter(contrato_m10__isnull=False)[:5]
for reg in registros_m10:
    print(f"ID: {reg.id:5d} | O.S: {reg.nr_ordem} | ID_CONTRATO: '{reg.id_contrato}' | FATURA: {reg.nr_fatura}")

# Verificar se tem zeros à esquerda
print("\n" + "="*80)
print("ANÁLISE DE ZEROS À ESQUERDA:")
print("="*80 + "\n")
amostra = ImportacaoFPD.objects.all()[:20]
with_zeros = 0
without_zeros = 0
for reg in amostra:
    if reg.id_contrato.startswith('0'):
        with_zeros += 1
        status = "✅ COM ZERO"
    else:
        without_zeros += 1
        status = "❌ SEM ZERO"
    print(f"{status} | ID_CONTRATO: '{reg.id_contrato}'")

print(f"\nRESULTADO: {with_zeros} com zeros, {without_zeros} sem zeros")
