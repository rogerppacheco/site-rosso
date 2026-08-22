"""
Script para testar importação de CHURN e verificar erros
"""
import os
import sys
import django
import pandas as pd
from datetime import datetime
import tkinter as tk
from tkinter import filedialog

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, ImportacaoChurn

def importar_churn():
    print("=" * 80)
    print("🔄 IMPORTADOR CHURN - TESTE E DEBUG")
    print("=" * 80)
    
    # Seletor de arquivo
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    arquivo = filedialog.askopenfilename(
        title="Selecione o arquivo CHURN",
        filetypes=[
            ("Excel files", "*.xlsx *.xls *.xlsb"),
            ("CSV files", "*.csv"),
            ("All files", "*.*")
        ]
    )
    
    if not arquivo:
        print("❌ Nenhum arquivo selecionado")
        return
    
    print(f"\n📂 Arquivo selecionado: {arquivo}")
    print(f"   Tamanho: {os.path.getsize(arquivo):,} bytes")
    
    try:
        # Ler arquivo
        print("\n📖 Lendo arquivo...")
        
        if arquivo.endswith('.csv'):
            df = pd.read_csv(arquivo, dtype={'NR_ORDEM': str})
        elif arquivo.endswith('.xlsb'):
            df = pd.read_excel(arquivo, engine='pyxlsb', dtype={'NR_ORDEM': str})
        else:
            df = pd.read_excel(arquivo, dtype={'NR_ORDEM': str})
        
        print(f"✅ Arquivo lido: {len(df)} linhas")
        
        # Normalizar colunas
        df.columns = df.columns.str.strip().str.upper()
        
        print(f"\n📋 Colunas encontradas ({len(df.columns)}):")
        for i, col in enumerate(df.columns, 1):
            print(f"   {i:2}. '{col}'")
        
        # Verificar se tem NR_ORDEM
        if 'NR_ORDEM' not in df.columns:
            print("\n❌ ERRO: Coluna NR_ORDEM não encontrada!")
            print("   Colunas disponíveis:", list(df.columns))
            return
        
        print("\n🔍 Primeiras 3 linhas da coluna NR_ORDEM:")
        for i, val in enumerate(df['NR_ORDEM'].head(3), 1):
            print(f"   Linha {i}: '{val}' (tipo: {type(val).__name__})")
        
        # Processar dados
        print("\n🔄 Processando registros...")
        
        cancelados = 0
        salvos_churn = 0
        reativados = 0
        nao_encontrados = 0
        erros = 0
        
        ordens_no_churn = set()
        
        for idx, row in df.iterrows():
            try:
                # Busca por O.S
                nr_ordem_raw = row.get('NR_ORDEM', '')
                if pd.isna(nr_ordem_raw) or str(nr_ordem_raw).strip() == '':
                    continue
                
                nr_ordem = str(nr_ordem_raw).strip().zfill(8)
                ordens_no_churn.add(nr_ordem)
                
                if idx < 3:  # Debug primeiras 3 linhas
                    print(f"\n📌 DEBUG Linha {idx + 1}:")
                    print(f"   RAW value: {nr_ordem_raw}")
                    print(f"   Processado: '{nr_ordem}'")
                
                # Salvar no ImportacaoChurn
                try:
                    numero_pedido = str(row.get('NUMERO_PEDIDO', '')) if pd.notna(row.get('NUMERO_PEDIDO')) else None
                    
                    obj, created = ImportacaoChurn.objects.update_or_create(
                        numero_pedido=numero_pedido,
                        defaults={
                            'nr_ordem': nr_ordem,
                            'uf': str(row.get('UF', ''))[:2] if pd.notna(row.get('UF')) else None,
                            'produto': str(row.get('PRODUTO', '')) if pd.notna(row.get('PRODUTO')) else None,
                            'matricula_vendedor': str(row.get('MATRICULA_VENDEDOR', '')) if pd.notna(row.get('MATRICULA_VENDEDOR')) else None,
                            'gv': str(row.get('GV', '')) if pd.notna(row.get('GV')) else None,
                            'dt_retirada': pd.to_datetime(row.get('DT_RETIRADA')).date() if pd.notna(row.get('DT_RETIRADA')) else None,
                            'motivo_retirada': str(row.get('MOTIVO_RETIRADA', '')) if pd.notna(row.get('MOTIVO_RETIRADA')) else None,
                        }
                    )
                    salvos_churn += 1
                    
                    if idx < 3:
                        print(f"   ✅ ImportacaoChurn {'CRIADO' if created else 'ATUALIZADO'} - ID: {obj.id}")
                    
                except Exception as e:
                    if idx < 3:
                        print(f"   ❌ Erro ao salvar ImportacaoChurn: {e}")
                    erros += 1
                
                # Atualizar ContratoM10
                try:
                    contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                    
                    if contrato.status_contrato != 'CANCELADO':
                        contrato.status_contrato = 'CANCELADO'
                        contrato.data_cancelamento = pd.to_datetime(row.get('DT_RETIRADA')).date() if pd.notna(row.get('DT_RETIRADA')) else datetime.now().date()
                        contrato.motivo_cancelamento = str(row.get('MOTIVO_RETIRADA', '')) if pd.notna(row.get('MOTIVO_RETIRADA')) else 'CHURN'
                        contrato.elegivel_bonus = False
                        contrato.save()
                        cancelados += 1
                        
                        if idx < 3:
                            print(f"   ✅ ContratoM10 marcado como CANCELADO: {contrato.cliente_nome}")
                    else:
                        if idx < 3:
                            print(f"   ℹ️  ContratoM10 já estava CANCELADO: {contrato.cliente_nome}")
                    
                except ContratoM10.DoesNotExist:
                    nao_encontrados += 1
                    if idx < 3:
                        print(f"   ⚠️  ContratoM10 NÃO encontrado para O.S {nr_ordem}")
                
            except Exception as e:
                erros += 1
                if idx < 3:
                    print(f"   ❌ Erro geral na linha {idx + 1}: {e}")
                continue
            
            # Progress
            if (idx + 1) % 100 == 0:
                print(f"⏳ Processadas {idx + 1}/{len(df)} linhas...")
        
        # Reativar contratos que não aparecem no CHURN
        print("\n🔄 Reativando contratos que não aparecem no CHURN...")
        contratos_ativos = ContratoM10.objects.exclude(ordem_servico__in=ordens_no_churn).exclude(status_contrato='ATIVO')
        reativados = contratos_ativos.update(status_contrato='ATIVO', data_cancelamento=None)
        
        print("\n" + "=" * 80)
        print("✅ PROCESSAMENTO CONCLUÍDO")
        print("=" * 80)
        print(f"\n📊 ESTATÍSTICAS:")
        print(f"   Total de linhas no arquivo: {len(df)}")
        print(f"   Registros salvos em ImportacaoChurn: {salvos_churn}")
        print(f"   Contratos marcados como CANCELADO: {cancelados}")
        print(f"   Contratos reativados (não no CHURN): {reativados}")
        print(f"   Contratos não encontrados no M10: {nao_encontrados}")
        print(f"   Erros: {erros}")
        print(f"   O.S únicas processadas: {len(ordens_no_churn)}")
        
    except Exception as e:
        import traceback
        print(f"\n❌ ERRO FATAL: {e}")
        print("\nTraceback completo:")
        traceback.print_exc()

if __name__ == '__main__':
    importar_churn()
    input("\nPressione ENTER para sair...")
