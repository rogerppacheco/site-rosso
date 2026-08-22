#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10

print("\n" + "="*80)
print("VERIFICAÇÃO FINAL - DADOS COM LEADING ZEROS")
print("="*80 + "\n")

# 1. Verificar ImportacaoFPD
print("📊 ImportacaoFPD - Amostra aleatória:")
print("-" * 80)
registros_fpd = ImportacaoFPD.objects.all()[:10]
for reg in registros_fpd:
    print(f"  O.S: {reg.nr_ordem} | ID_CONTRATO: '{reg.id_contrato}' | FATURA: {reg.nr_fatura}")

# 2. Verificar ContratoM10
print("\n📊 ContratoM10 - Registros com número definitivo:")
print("-" * 80)
contratos = ContratoM10.objects.filter(numero_contrato_definitivo__isnull=False)[:10]
for contrato in contratos:
    print(f"  O.S: {contrato.ordem_servico} | Nº Contrato Definitivo: '{contrato.numero_contrato_definitivo}'")

# 3. Estatísticas
print("\n📈 ESTATÍSTICAS FINAIS:")
print("-" * 80)
total_fpd = ImportacaoFPD.objects.count()
total_com_m10 = ImportacaoFPD.objects.filter(contrato_m10__isnull=False).count()
total_sem_m10 = ImportacaoFPD.objects.filter(contrato_m10__isnull=True).count()
contratos_com_num = ContratoM10.objects.filter(numero_contrato_definitivo__isnull=False).count()

print(f"  Total em ImportacaoFPD: {total_fpd}")
print(f"  - Com vínculo M10: {total_com_m10}")
print(f"  - Sem vínculo M10: {total_sem_m10}")
print(f"  ContratoM10 com Nº Definitivo: {contratos_com_num}")

# 4. Verificação de zeros
print("\n✅ VERIFICAÇÃO DE LEADING ZEROS:")
print("-" * 80)
amostra = ImportacaoFPD.objects.all()[:20]
com_zeros = 0
sem_zeros = 0
for reg in amostra:
    if reg.id_contrato.startswith('0'):
        com_zeros += 1
    else:
        sem_zeros += 1

print(f"  Amostra de 20 registros:")
print(f"  - Com leading zero: {com_zeros} ✅")
print(f"  - Sem leading zero: {sem_zeros}")

if com_zeros == 20 and sem_zeros == 0:
    print(f"\n🎉 SUCESSO! Todos os IDs têm leading zeros preservados!")
else:
    print(f"\n⚠️  Atenção: Nem todos os IDs têm leading zeros")

print("\n" + "="*80)
