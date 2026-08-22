#!/usr/bin/env python
"""
ANÁLISE DO PROBLEMA DE ZEROS NO ID_CONTRATO

DESCOBERTA:
O arquivo FPD.xlsb armazena ID_CONTRATO como tipo INT64 (número inteiro).
Isso significa que os zeros à esquerda JÁ foram perdidos no arquivo original.

Exemplos:
- 02055873 → 2055873 (Excel salvou como número, perdendo o leading zero)
- 07309961 → 7309961 (nunca teve zero? ou foi removido?)

PERGUNTA IMPORTANTE:
Você tem:
1. Backup do arquivo FPD com os dados originais (XLSX/CSV com texto)?
2. Banco de dados de origem do FPD na NIO com os valores corretos?
3. Documento de especificação indicando o formato esperado?

OPÇÕES DE SOLUÇÃO:
1. Se houver arquivo original em texto: reimportar com preservação de texto
2. Se houver banco de origem: fazer sync direto do banco NIO
3. Se houver especificação: documentar o formato e aplicar lógica de padding
   (ex: sempre padronizar para 8 dígitos com zfill(8))

PRÓXIMOS PASSOS:
- Verificar qual é a source of truth para esses dados
- Determinar se 02055873 é realmente o número correto
- Implementar solução apropriada
"""

import os
import subprocess

# Listar arquivos na área de trabalho do usuário
desktop_path = r"C:\Users\rogge\OneDrive\Área de Trabalho"

print("="*80)
print("ARQUIVOS NA ÁREA DE TRABALHO (Desktop)")
print("="*80 + "\n")

if os.path.exists(desktop_path):
    arquivos = os.listdir(desktop_path)
    fpd_files = [f for f in arquivos if 'fpd' in f.lower() or 'contrat' in f.lower()]
    
    print(f"Total de arquivos: {len(arquivos)}")
    print(f"\nArquivos relacionados a FPD ou contrato:")
    for f in fpd_files:
        path = os.path.join(desktop_path, f)
        size = os.path.getsize(path)
        print(f"  - {f} ({size:,} bytes)")
else:
    print(f"Caminho não encontrado: {desktop_path}")

# Verificar se há backups do banco
print("\n" + "="*80)
print("BACKUPS DO BANCO DE DADOS")
print("="*80 + "\n")

backup_files = [
    "c:\\site-record\\backup_recordpap.sql",
    "c:\\site-record\\backup_final.sql",
    "c:\\site-record\\meu_backup_producao.sql",
]

for bf in backup_files:
    if os.path.exists(bf):
        size = os.path.getsize(bf)
        print(f"✅ {bf} ({size:,} bytes)")
    else:
        print(f"❌ {bf} (não encontrado)")
