"""
Script de debug para testar importação FPD manualmente
"""

import os
import django
import pandas as pd

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10
from django.utils import timezone

# Pedir caminho do arquivo
arquivo_path = input("Digite o caminho do arquivo FPD (ex: C:\\Users\\...\\1067098.xlsb): ").strip()

if not os.path.exists(arquivo_path):
    print(f"❌ Arquivo não encontrado: {arquivo_path}")
    exit(1)

print(f"\n📂 Lendo arquivo: {arquivo_path}")

# Ler arquivo
try:
    if arquivo_path.endswith('.xlsb'):
        df = pd.read_excel(arquivo_path, engine='pyxlsb')
    elif arquivo_path.endswith('.csv'):
        df = pd.read_csv(arquivo_path)
    else:
        df = pd.read_excel(arquivo_path)
    
    print(f"✅ Arquivo lido: {len(df)} linhas")
except Exception as e:
    print(f"❌ Erro ao ler arquivo: {str(e)}")
    exit(1)

# Mostrar colunas
print(f"\n📋 Colunas do arquivo:")
for col in df.columns:
    print(f"   - {col}")

# Verificar se tem coluna NR_ORDEM
if 'NR_ORDEM' not in df.columns:
    print("\n❌ ERRO: Coluna 'NR_ORDEM' não encontrada!")
    print("   Colunas disponíveis:", list(df.columns))
    exit(1)

# Processar primeiras 5 linhas para debug
print(f"\n🔍 Processando primeiras 5 linhas (DEBUG):\n")

registros_criados = 0
registros_atualizados = 0
registros_sem_contrato = 0
erros = []

for idx in range(min(5, len(df))):
    row = df.iloc[idx]
    
    print(f"Linha {idx + 1}:")
    
    # Pegar O.S
    nr_ordem = str(row.get('NR_ORDEM', '')).strip()
    print(f"   NR_ORDEM raw: '{row.get('NR_ORDEM')}'")
    print(f"   NR_ORDEM processado: '{nr_ordem}'")
    
    if not nr_ordem or nr_ordem == 'nan':
        print(f"   ❌ Vazio ou 'nan' - PULANDO\n")
        continue
    
    # Buscar contrato M10
    print(f"   Buscando ContratoM10 com ordem_servico='{nr_ordem}'...")
    
    try:
        contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
        print(f"   ✅ Contrato encontrado: {contrato.cliente_nome}")
        
        # Extrair dados
        nr_fatura = str(row.get('NR_FATURA', '')).strip()
        vl_fatura = row.get('VL_FATURA', 0)
        
        print(f"   NR_FATURA: {nr_fatura}")
        print(f"   VL_FATURA: {vl_fatura}")
        
        # Tentar salvar
        try:
            dt_venc = row.get('DT_VENC_ORIG')
            dt_venc_date = pd.to_datetime(dt_venc).date() if pd.notna(dt_venc) else timezone.now().date()
            
            importacao_fpd, criado = ImportacaoFPD.objects.update_or_create(
                nr_ordem=nr_ordem,
                nr_fatura=nr_fatura,
                defaults={
                    'id_contrato': str(row.get('ID_CONTRATO', '')).strip(),
                    'dt_venc_orig': dt_venc_date,
                    'dt_pagamento': pd.to_datetime(row.get('DT_PAGAMENTO')).date() if pd.notna(row.get('DT_PAGAMENTO')) else None,
                    'nr_dias_atraso': int(row.get('NR_DIAS_ATRASO', 0)) if pd.notna(row.get('NR_DIAS_ATRASO')) else 0,
                    'ds_status_fatura': str(row.get('DS_STATUS_FATURA', 'NAO_PAGO')).upper(),
                    'vl_fatura': float(vl_fatura) if pd.notna(vl_fatura) else 0,
                    'contrato_m10': contrato,
                }
            )
            
            if criado:
                print(f"   ✅ ImportacaoFPD CRIADA (ID: {importacao_fpd.id})")
                registros_criados += 1
            else:
                print(f"   ✅ ImportacaoFPD ATUALIZADA (ID: {importacao_fpd.id})")
                registros_atualizados += 1
                
        except Exception as e:
            print(f"   ❌ Erro ao salvar ImportacaoFPD: {str(e)}")
            erros.append(f"Linha {idx+1}: {str(e)}")
        
    except ContratoM10.DoesNotExist:
        print(f"   ⚠️  ContratoM10 NÃO encontrado - Salvando sem vínculo...")
        
        # Salvar sem contrato
        try:
            nr_fatura = str(row.get('NR_FATURA', '')).strip()
            dt_venc = row.get('DT_VENC_ORIG')
            dt_venc_date = pd.to_datetime(dt_venc).date() if pd.notna(dt_venc) else timezone.now().date()
            
            importacao_fpd, criado = ImportacaoFPD.objects.update_or_create(
                nr_ordem=nr_ordem,
                nr_fatura=nr_fatura,
                defaults={
                    'id_contrato': str(row.get('ID_CONTRATO', '')).strip(),
                    'dt_venc_orig': dt_venc_date,
                    'dt_pagamento': pd.to_datetime(row.get('DT_PAGAMENTO')).date() if pd.notna(row.get('DT_PAGAMENTO')) else None,
                    'nr_dias_atraso': int(row.get('NR_DIAS_ATRASO', 0)) if pd.notna(row.get('NR_DIAS_ATRASO')) else 0,
                    'ds_status_fatura': str(row.get('DS_STATUS_FATURA', 'NAO_PAGO')).upper(),
                    'vl_fatura': float(row.get('VL_FATURA', 0)) if pd.notna(row.get('VL_FATURA')) else 0,
                    'contrato_m10': None,
                }
            )
            
            if criado:
                print(f"   ✅ ImportacaoFPD CRIADA sem M10 (ID: {importacao_fpd.id})")
                registros_sem_contrato += 1
            else:
                print(f"   ✅ ImportacaoFPD ATUALIZADA sem M10 (ID: {importacao_fpd.id})")
                registros_atualizados += 1
                
        except Exception as e:
            print(f"   ❌ Erro ao salvar sem M10: {str(e)}")
            erros.append(f"Linha {idx+1} (sem M10): {str(e)}")
    
    print()

print("=" * 80)
print(f"✅ Registros criados: {registros_criados}")
print(f"✅ Registros atualizados: {registros_atualizados}")
print(f"⚠️  Registros sem contrato M10: {registros_sem_contrato}")
print(f"❌ Erros: {len(erros)}")

if erros:
    print("\nErros encontrados:")
    for erro in erros:
        print(f"   - {erro}")

# Verificar se salvou no banco
total_fpd = ImportacaoFPD.objects.count()
print(f"\n📊 Total de registros em ImportacaoFPD: {total_fpd}")
