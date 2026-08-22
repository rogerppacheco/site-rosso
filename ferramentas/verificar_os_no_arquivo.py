"""
Script para verificar se uma O.S específica está no arquivo FPD
"""
import pandas as pd
from pathlib import Path
import sys

def verificar_os_no_arquivo(numero_os, arquivo='1067098.xlsb'):
    print("=" * 80)
    print(f"🔍 VERIFICANDO O.S {numero_os} NO ARQUIVO {arquivo}")
    print("=" * 80)
    print()
    
    # Verificar se arquivo existe
    if not Path(arquivo).exists():
        print(f"❌ Arquivo '{arquivo}' não encontrado!")
        print(f"   Caminho atual: {Path.cwd()}")
        print()
        print("Arquivos .xls* disponíveis:")
        for f in Path('.').glob('*.xls*'):
            print(f"   • {f.name}")
        return
    
    try:
        # Ler arquivo
        print(f"📄 Lendo arquivo {arquivo}...")
        if arquivo.endswith('.xlsb'):
            df = pd.read_excel(arquivo, engine='pyxlsb')
        else:
            df = pd.read_excel(arquivo)
        
        print(f"✅ Arquivo lido com sucesso!")
        print(f"   Total de linhas: {len(df)}")
        print(f"   Colunas: {list(df.columns)}")
        print()
        
        # Verificar se coluna nr_ordem existe
        if 'nr_ordem' not in df.columns:
            print(f"❌ Coluna 'nr_ordem' não encontrada!")
            print(f"   Colunas disponíveis: {list(df.columns)}")
            return
        
        # Buscar O.S
        print(f"🔎 Buscando O.S '{numero_os}'...")
        print()
        
        # Converter para string e limpar
        df['nr_ordem_str'] = df['nr_ordem'].astype(str).str.strip()
        
        # Variações
        variacoes = [
            numero_os,
            numero_os.lstrip('0'),
            f"OS-{numero_os}",
            f"OS-{numero_os.lstrip('0')}",
        ]
        
        encontrou = False
        for variacao in variacoes:
            resultado = df[df['nr_ordem_str'].str.contains(variacao, case=False, na=False)]
            
            if not resultado.empty:
                encontrou = True
                print(f"✅ ENCONTRADO com variação '{variacao}':")
                print(f"   Total de ocorrências: {len(resultado)}")
                print()
                
                for idx, row in resultado.iterrows():
                    print(f"   📋 Registro {idx + 1}:")
                    for col in df.columns:
                        if col != 'nr_ordem_str':
                            valor = row[col]
                            if pd.notna(valor):
                                print(f"      {col}: {valor}")
                    print()
        
        if not encontrou:
            print(f"❌ O.S '{numero_os}' NÃO ENCONTRADA no arquivo!")
            print()
            print("📊 Amostra das primeiras 10 O.S do arquivo:")
            for i, os in enumerate(df['nr_ordem'].head(10), 1):
                print(f"   {i:2d}. {os}")
            print()
            print("💡 Verifique se o número está correto ou se é de outro arquivo")
        
    except Exception as e:
        print(f"❌ Erro ao processar arquivo: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        numero = sys.argv[1]
    else:
        numero = input("Digite o número da O.S (ou Enter para 07309961): ").strip()
        if not numero:
            numero = "07309961"
    
    arquivo = input("Digite o nome do arquivo (ou Enter para 1067098.xlsb): ").strip()
    if not arquivo:
        arquivo = "1067098.xlsb"
    
    verificar_os_no_arquivo(numero, arquivo)
