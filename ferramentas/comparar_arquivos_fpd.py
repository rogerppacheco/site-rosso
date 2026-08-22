#!/usr/bin/env python
import pandas as pd
import os

print("="*80)
print("COMPARAÇÃO DE ARQUIVOS FPD")
print("="*80 + "\n")

files_to_check = [
    (r"C:\Users\rogge\OneDrive\Área de Trabalho\FPD.xlsb", "FPD.xlsb"),
    (r"C:\Users\rogge\OneDrive\Área de Trabalho\FPD_INOVA MG_APURAÇÃO_1068281.xlsb", "FPD_INOVA MG_APURAÇÃO_1068281.xlsb"),
    (r"C:\Users\rogge\OneDrive\Área de Trabalho\FPD_INOVA MG_APURAÇÃO_1068281.xlsb.xlsx", "FPD_INOVA MG_APURAÇÃO_1068281.xlsb.xlsx"),
]

for filepath, filename in files_to_check:
    if not os.path.exists(filepath):
        print(f"❌ Não encontrado: {filename}")
        continue
    
    print(f"\n{'='*80}")
    print(f"ARQUIVO: {filename}")
    print(f"{'='*80}\n")
    
    try:
        # Ler com engine apropriado
        if filepath.endswith('.xlsx'):
            df = pd.read_excel(filepath)
        else:
            df = pd.read_excel(filepath, engine='pyxlsb')
        
        # Normalizar colunas
        df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')
        
        # Procurar coluna ID_CONTRATO
        contrato_cols = [col for col in df.columns if 'contrato' in col]
        
        if not contrato_cols:
            print(f"Aviso: Nenhuma coluna 'contrato' encontrada")
            print(f"Colunas disponíveis: {list(df.columns[:10])}")
            continue
        
        col = contrato_cols[0]
        print(f"Total de linhas: {len(df)}")
        print(f"Coluna encontrada: '{col}'")
        print(f"Tipo de dados: {df[col].dtype}")
        
        print(f"\nPrimeiros 10 valores de {col}:")
        for i, val in enumerate(df[col].head(10), 1):
            str_val = str(val)
            has_zero = str_val.startswith('0')
            print(f"  {i}. {str_val:>10} | Começa com 0: {has_zero}")
        
        # Estatísticas
        print(f"\nEstatísticas:")
        print(f"  Máximo: {df[col].max()}")
        print(f"  Mínimo: {df[col].min()}")
        print(f"  Valores únicos: {df[col].nunique()}")
        print(f"  NaNs: {df[col].isna().sum()}")
        
    except Exception as e:
        print(f"❌ Erro ao ler: {str(e)}")

print("\n" + "="*80)
print("CONCLUSÃO")
print("="*80 + "\n")
print("""
Se TODOS os arquivos mostram ID_CONTRATO como INT64 e SEM zeros,
significa que:

1. Os zeros foram perdidos no Excel (formato numérico em vez de texto)
2. A fonte de dados original (NIO) não tem esses zeros
3. Os zeros NÃO são necessários para esse campo

RECOMENDAÇÃO:
Se você precisa dos zeros, você deve:
- Consultarc com NIO qual é o formato correto
- Ou usar banco de dados de origem (se disponível)
- Ou assumir que o formato SEM zeros é o correto
""")
