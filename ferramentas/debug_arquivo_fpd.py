"""
Debug rápido para verificar conteúdo do arquivo FPD
"""
import pandas as pd
from tkinter import filedialog, Tk

# Abrir janela de seleção
root = Tk()
root.withdraw()
arquivo = filedialog.askopenfilename(
    title="Selecione o arquivo FPD",
    filetypes=[("Excel", "*.xlsx *.xls *.xlsb"), ("CSV", "*.csv"), ("Todos", "*.*")]
)
root.destroy()

if not arquivo:
    print("❌ Nenhum arquivo selecionado")
    exit()

print(f"📂 Arquivo: {arquivo}\n")

# Ler arquivo
if arquivo.endswith('.xlsb'):
    df = pd.read_excel(arquivo, engine='pyxlsb')
elif arquivo.endswith('.csv'):
    df = pd.read_csv(arquivo)
else:
    df = pd.read_excel(arquivo)

print(f"✅ {len(df)} linhas lidas\n")

# Normalizar
df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')

print(f"📋 COLUNAS ({len(df.columns)}):")
for i, col in enumerate(df.columns, 1):
    print(f"   {i:2d}. '{col}'")

print(f"\n🔍 COLUNA 'nr_ordem' existe? {'SIM' if 'nr_ordem' in df.columns else 'NÃO'}")

if 'nr_ordem' in df.columns:
    print(f"\n📊 ANÁLISE DA COLUNA 'nr_ordem':")
    print(f"   Tipo de dados: {df['nr_ordem'].dtype}")
    print(f"   Total de valores: {len(df['nr_ordem'])}")
    print(f"   Valores vazios (NaN): {df['nr_ordem'].isna().sum()}")
    print(f"   Valores não vazios: {df['nr_ordem'].notna().sum()}")
    
    # Primeiros 10 valores
    print(f"\n📌 PRIMEIROS 10 VALORES:")
    for i, val in enumerate(df['nr_ordem'].head(10)):
        tipo = type(val).__name__
        val_str = str(val).strip()
        e_valido = val_str and val_str != 'nan' and val_str.lower() != 'none'
        print(f"   Linha {i+1}: '{val}' | tipo: {tipo} | válido: {'✅' if e_valido else '❌'}")
    
    # Estatísticas
    valores_unicos = df['nr_ordem'].nunique()
    print(f"\n📈 ESTATÍSTICAS:")
    print(f"   Valores únicos: {valores_unicos}")
    
    # Exemplos de valores válidos
    valores_validos = df[df['nr_ordem'].notna()]['nr_ordem'].head(5)
    print(f"\n✅ EXEMPLOS DE VALORES VÁLIDOS:")
    for val in valores_validos:
        print(f"   {val}")
else:
    print("\n❌ COLUNA 'nr_ordem' NÃO ENCONTRADA!")
    print("\n💡 Procurando colunas similares:")
    for col in df.columns:
        if 'ordem' in col.lower():
            print(f"   - {col}")

input("\n\nPressione ENTER para fechar...")
