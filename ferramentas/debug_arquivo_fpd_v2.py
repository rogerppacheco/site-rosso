#!/usr/bin/env python
import pandas as pd

# Ler arquivo Excel e verificar tipos de dados
arquivo = r"C:\Users\rogge\OneDrive\Área de Trabalho\FPD.xlsb"

# Ler sem converters primeiro para ver como pandas interpreta
print("="*80)
print("COLUNAS DO ARQUIVO ORIGINAL")
print("="*80 + "\n")

df = pd.read_excel(arquivo, engine='pyxlsb')

print(f"Total de colunas: {len(df.columns)}")
print("\nNomes exatos das colunas:")
for i, col in enumerate(df.columns, 1):
    print(f"  {i}. '{col}'")

# Normalizar para minúsculas
print("\n" + "="*80)
print("COLUNAS APÓS NORMALIZAÇÃO (lowercase)")
print("="*80 + "\n")

df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')

print(f"Total de colunas: {len(df.columns)}")
print("\nNomes normalizados:")
for i, col in enumerate(df.columns, 1):
    print(f"  {i}. '{col}'")

# Procurar por coluna que contenha 'contrato'
contrato_cols = [col for col in df.columns if 'contrato' in col]
print(f"\nColunas que contêm 'contrato': {contrato_cols}")

if contrato_cols:
    print("\n" + "="*80)
    print("ANÁLISE DA COLUNA DE CONTRATO")
    print("="*80 + "\n")
    
    col = contrato_cols[0]
    print(f"Coluna: '{col}'")
    print(f"Tipo de dados: {df[col].dtype}")
    print(f"\nPrimeiros 10 valores:")
    for i, val in enumerate(df[col].head(10), 1):
        str_val = str(val)
        has_zero = str_val.startswith('0')
        print(f"  {i}. Value: {val!r} | String: '{str_val}' | Starts with 0: {has_zero}")
