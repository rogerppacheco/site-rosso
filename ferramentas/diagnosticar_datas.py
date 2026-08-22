#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ImportacaoFPD

# Verificar datas nos registros FPD
print("\n" + "="*80)
print("VERIFICAÇÃO DE DATAS NO IMPORTAÇÃO FPD")
print("="*80 + "\n")

amostra = ImportacaoFPD.objects.filter(contrato_m10__isnull=False)[:10]

for fpd in amostra:
    print(f"O.S: {fpd.nr_ordem}")
    print(f"  dt_venc_orig: {fpd.dt_venc_orig} (tipo: {type(fpd.dt_venc_orig)})")
    print(f"  dt_pagamento: {fpd.dt_pagamento} (tipo: {type(fpd.dt_pagamento)})")
    print()

# Também verificar os dados raw do arquivo
print("\n" + "="*80)
print("ANÁLISE DO ARQUIVO FPD")
print("="*80 + "\n")

import pandas as pd

arquivo = r"C:\Users\rogge\OneDrive\Área de Trabalho\FPD.xlsb"

dtype_spec = {
    'ID_CONTRATO': str,
    'NR_FATURA': str,
    'NR_ORDEM': str,
}

df = pd.read_excel(arquivo, engine='pyxlsb', dtype=dtype_spec)
df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')

print(f"Tipo de dt_venc_orig: {df['dt_venc_orig'].dtype}")
print(f"Primeiros 5 valores:\n{df['dt_venc_orig'].head()}")

print(f"\nTipo de dt_pagamento: {df['dt_pagamento'].dtype}")
print(f"Primeiros 5 valores:\n{df['dt_pagamento'].head()}")

# Verificar alguns com zoom
print(f"\n" + "="*80)
print("ANÁLISE DETALHADA")
print("="*80 + "\n")

for i, row in df.head(5).iterrows():
    print(f"Linha {i+1}:")
    print(f"  dt_venc_orig: {row['dt_venc_orig']} (tipo: {type(row['dt_venc_orig']).__name__})")
    print(f"  dt_pagamento: {row['dt_pagamento']} (tipo: {type(row['dt_pagamento']).__name__})")
