import pandas as pd
import os
path = r'C:\Users\rogge\Downloads\Planilha Vendas_Clientes (2).xlsx'
if not os.path.exists(path):
    path = r'C:\Users\rogge\Downloads\Planilha Vendas_Clientes (2).csv'
df = pd.read_excel(path)
print(list(df.columns))
print(df.head(2))
