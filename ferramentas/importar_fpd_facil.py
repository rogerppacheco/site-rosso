"""
Script super simples para importar FPD - Janela de seleção de arquivo
"""

import os
import django
import pandas as pd
from decimal import Decimal
from tkinter import filedialog, Tk, messagebox
import tkinter as tk


def normalize_str(value):
    """Converte para string mantendo zeros à esquerda; remove sufixo .0 de floats."""
    if pd.isna(value):
        return ''
    s = str(value).strip()
    # Remover sufixo .0 apenas se for numérico puro (não para ID_CONTRATO)
    if s.endswith('.0') and s[:-2].isdigit():
        s = s[:-2]
    return s


def preserve_zeros_str(value):
    """Preserva string exatamente como está, sem conversão numérica."""
    if pd.isna(value):
        return ''
    return str(value).strip()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10, LogImportacaoFPD
from django.utils import timezone
from usuarios.models import Usuario
from fpd_status_mapping import normalizar_status_fpd


def importar_fpd_terminal(arquivo_path, usuario_id=None):
    """
    Importa arquivo FPD com validação e atualização
    """
    
    print("\n" + "=" * 100)
    print("📥 IMPORTAÇÃO FPD VIA TERMINAL")
    print("=" * 100)
    
    # Verificar arquivo
    if not os.path.exists(arquivo_path):
        print(f"❌ ERRO: Arquivo não encontrado: {arquivo_path}")
        return False
    
    print(f"\n📂 Arquivo: {arquivo_path}")
    print(f"   Tamanho: {os.path.getsize(arquivo_path):,} bytes")
    
    # Obter usuário
    usuario = None
    if usuario_id:
        try:
            usuario = Usuario.objects.get(id=usuario_id)
            print(f"   Usuário: {usuario.username}")
        except Usuario.DoesNotExist:
            print(f"   ⚠️  Usuário ID {usuario_id} não encontrado, continuando sem usuário")
    
    # Criar log
    log = LogImportacaoFPD.objects.create(
        nome_arquivo=os.path.basename(arquivo_path),
        tamanho_arquivo=os.path.getsize(arquivo_path),
        usuario=usuario,
        status='PROCESSANDO'
    )
    print(f"   Log ID: {log.id}")
    
    inicio = timezone.now()
    
    try:
        # Ler arquivo
        print(f"\n📖 Lendo arquivo...")
        
        # IMPORTANTE: Ler colunas numéricas como STRING para preservar leading zeros
        # ID_CONTRATO e NR_FATURA vêm com zeros à esquerda no arquivo
        dtype_spec = {
            'ID_CONTRATO': str,      # Força leitura como texto
            'NR_FATURA': str,        # Força leitura como texto
            'NR_ORDEM': str,         # Força leitura como texto
        }

        if arquivo_path.endswith('.csv'):
            df = pd.read_csv(arquivo_path, dtype=dtype_spec)
        elif arquivo_path.endswith('.xlsb'):
            try:
                df = pd.read_excel(arquivo_path, engine='pyxlsb', dtype=dtype_spec)
            except Exception as e:
                raise Exception(f'Formato .xlsb não suportado ou erro ao ler: {str(e)}')
        else:
            df = pd.read_excel(arquivo_path, dtype=dtype_spec)
        
        print(f"✅ Arquivo lido: {len(df)} linhas")
        
        # Normalizar nomes de colunas para minúsculas E remover espaços extras
        df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')
        
        # Mostrar colunas
        print(f"\n📋 Colunas encontradas ({len(df.columns)}):")
        for i, col in enumerate(df.columns, 1):
            print(f"   {i:2d}. '{col}'")
        
        # Mostrar primeiras 3 linhas de NR_ORDEM para debug
        if 'nr_ordem' in df.columns:
            print(f"\n🔍 Primeiras 3 linhas da coluna NR_ORDEM:")
            for i, val in enumerate(df['nr_ordem'].head(3)):
                print(f"   Linha {i+1}: '{val}' (tipo: {type(val).__name__})")
        
        # Verificar coluna nr_ordem
        if 'nr_ordem' not in df.columns:
            print(f"\n❌ ERRO: Coluna 'nr_ordem' não encontrada!")
            print(f"   Colunas disponíveis: {', '.join(df.columns)}")
            raise Exception("Coluna 'nr_ordem' não encontrada no arquivo")
        
        log.total_linhas = len(df)
        log.save(update_fields=['total_linhas'])
        
        # Contadores
        criados = 0
        atualizados = 0
        com_contrato = 0
        sem_contrato = 0
        pulados = 0
        erros = 0
        valor_total = 0
        
        erros_detalhados = []
        os_nao_encontradas = []
        
        # Processar linhas
        print(f"\n🔄 Processando {len(df)} linhas...")
        print("-" * 100)
        
        for idx, row in df.iterrows():
            try:
                # Extrair nr_ordem (agora já vem como string graças ao dtype=str)
                nr_ordem_raw = row.get('nr_ordem', '')
                
                # Debug: Mostrar valor bruto nas primeiras linhas
                if idx < 3:
                    print(f"\n📌 DEBUG Linha {idx + 1}:")
                    print(f"   RAW value: {repr(nr_ordem_raw)}")
                    print(f"   RAW type: {type(nr_ordem_raw).__name__}")
                    print(f"   Is NaN? {pd.isna(nr_ordem_raw) if not isinstance(nr_ordem_raw, str) else False}")
                
                # Verificar se é vazio
                if not nr_ordem_raw or not str(nr_ordem_raw).strip():
                    if idx < 3:
                        print(f"   ⚠️  PULANDO - valor é vazio")
                    pulados += 1
                    continue
                
                # Converter para string mas MANTER ZEROS à esquerda
                nr_ordem = str(nr_ordem_raw).strip()
                
                # Validar NR_ORDEM
                if not nr_ordem or nr_ordem == 'nan' or nr_ordem.lower() == 'none' or nr_ordem == '':
                    if idx < 3:
                        print(f"   ⚠️  PULANDO - NR_ORDEM vazio ou inválido: '{nr_ordem}'")
                    pulados += 1
                    continue
                
                # Se for número, adicionar zero à esquerda para padronizar em 8 dígitos
                if nr_ordem.replace('.', '').replace('-', '').isdigit():
                    # Remover ".0" se existir (vem do pandas quando lê números do Excel)
                    nr_ordem = nr_ordem.split('.')[0]
                    nr_ordem = nr_ordem.zfill(8)  # Preenche com zeros à esquerda até 8 dígitos
                
                if idx < 3:
                    print(f"   ✅ NR_ORDEM processado: '{nr_ordem}' (8 dígitos: {len(nr_ordem) == 8})")
                
                # Extrair outros campos - agora já vêm como STRING graças ao dtype
                # Não precisa mais de normalize_str/preserve_zeros_str, pois já são strings
                nr_fatura = str(row.get('nr_fatura', '')).strip()
                id_contrato = str(row.get('id_contrato', '')).strip()
                
                # Datas - Excel armazena como números serial (dias desde 1900-01-01)
                # Converter de número serial Excel para datetime
                dt_venc = row.get('dt_venc_orig')
                if pd.notna(dt_venc):
                    # Se for número, converter de serial Excel
                    if isinstance(dt_venc, (int, float)):
                        dt_venc_date = pd.Timestamp("1900-01-01") + pd.Timedelta(days=dt_venc - 2)
                        dt_venc_date = dt_venc_date.date()
                    else:
                        dt_venc_date = pd.to_datetime(dt_venc).date()
                else:
                    dt_venc_date = timezone.now().date()
                
                dt_pgto = row.get('dt_pagamento')
                if pd.notna(dt_pgto):
                    # Se for número, converter de serial Excel
                    if isinstance(dt_pgto, (int, float)):
                        dt_pgto_date = pd.Timestamp("1900-01-01") + pd.Timedelta(days=dt_pgto - 2)
                        dt_pgto_date = dt_pgto_date.date()
                    else:
                        dt_pgto_date = pd.to_datetime(dt_pgto).date()
                else:
                    dt_pgto_date = None
                
                # Valores
                vl_fatura = row.get('vl_fatura', 0)
                if pd.isna(vl_fatura):
                    vl_fatura = 0
                vl_fatura_float = float(vl_fatura) if vl_fatura else 0
                
                nr_dias_atraso = row.get('nr_dias_atraso', 0)
                nr_dias_atraso_int = int(nr_dias_atraso) if pd.notna(nr_dias_atraso) else 0
                
                # Status - Normalizar usando mapeamento padronizado
                status_str = str(row.get('ds_status_fatura', 'NAO_PAGO')).upper()
                status = normalizar_status_fpd(status_str)  # PAGO, NAO_PAGO, AGUARDANDO, ATRASADO, OUTROS
                
                if idx < 5:
                    print(f"   Fatura: {nr_fatura}")
                    print(f"   Valor: R$ {vl_fatura_float:,.2f}")
                    print(f"   Status: {status_str}")
                
                # Buscar ContratoM10
                contrato = None
                try:
                    # Tentar busca exata primeiro
                    contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                except ContratoM10.DoesNotExist:
                    # Se não encontrar, tentar sem o zero à esquerda (para compatibilidade)
                    nr_ordem_sem_zero = nr_ordem.lstrip('0') or '0'
                    try:
                        contrato = ContratoM10.objects.get(ordem_servico=nr_ordem_sem_zero)
                    except ContratoM10.DoesNotExist:
                        pass
                
                if idx < 5:
                    if contrato:
                        print(f"   ✅ ContratoM10 encontrado: {contrato.cliente_nome}")
                    else:
                        print(f"   ⚠️  ContratoM10 NÃO encontrado para O.S {nr_ordem}")
                
                # Verificar se já existe
                ja_existe = ImportacaoFPD.objects.filter(
                    nr_ordem=nr_ordem,
                    nr_fatura=nr_fatura
                ).exists()
                
                if idx < 5:
                    print(f"   ImportacaoFPD já existe? {'SIM' if ja_existe else 'NÃO'}")
                
                # Salvar ou atualizar
                importacao_fpd, criado = ImportacaoFPD.objects.update_or_create(
                    nr_ordem=nr_ordem,
                    nr_fatura=nr_fatura,
                    defaults={
                        'id_contrato': id_contrato,
                        'dt_venc_orig': dt_venc_date,
                        'dt_pagamento': dt_pgto_date,
                        'nr_dias_atraso': nr_dias_atraso_int,
                        'ds_status_fatura': status_str,  # Status original do FPD (para rastreabilidade)
                        'vl_fatura': Decimal(str(vl_fatura_float)),
                        'contrato_m10': contrato,
                    }
                )
                
                # Se tem vínculo M10, atualizar/criar FaturaM10 (fatura 1)
                if contrato:
                    from crm_app.models import FaturaM10
                    fatura_m10, _ = FaturaM10.objects.update_or_create(
                        contrato=contrato,
                        numero_fatura=1,  # FPD é apenas da fatura 1
                        defaults={
                            'numero_fatura_operadora': nr_fatura,
                            'data_vencimento': dt_venc_date,
                            'data_pagamento': dt_pgto_date,
                            'dias_atraso': nr_dias_atraso_int,
                            'status': status,  # Status normalizado para o sistema
                            'valor': Decimal(str(vl_fatura_float)),
                            'id_contrato_fpd': id_contrato,
                            'dt_pagamento_fpd': dt_pgto_date,
                            'ds_status_fatura_fpd': status_str,  # Status original do FPD (para rastreabilidade)
                            'data_importacao_fpd': timezone.now(),
                        }
                    )
                
                # Contabilizar
                if criado:
                    criados += 1
                    if idx < 5:
                        print(f"   ✅ CRIADO - ImportacaoFPD ID: {importacao_fpd.id}")
                else:
                    atualizados += 1
                    if idx < 5:
                        print(f"   ✅ ATUALIZADO - ImportacaoFPD ID: {importacao_fpd.id}")
                
                if contrato:
                    com_contrato += 1
                else:
                    sem_contrato += 1
                    if len(os_nao_encontradas) < 20:
                        os_nao_encontradas.append(nr_ordem)
                
                valor_total += vl_fatura_float
                
                # Mostrar progresso a cada 100 linhas
                if (idx + 1) % 100 == 0:
                    print(f"\n⏳ Processadas {idx + 1}/{len(df)} linhas... (Criados: {criados}, Atualizados: {atualizados})")
                
            except Exception as e:
                erros += 1
                erro_msg = f"Linha {idx + 1}: {str(e)}"
                erros_detalhados.append(erro_msg)
                if erros <= 10:
                    print(f"\n❌ ERRO - {erro_msg}")
        
        # Finalizar
        print("\n" + "=" * 100)
        print("✅ PROCESSAMENTO CONCLUÍDO")
        print("=" * 100)
        
        print(f"\n📊 ESTATÍSTICAS:")
        print(f"   Total de linhas no arquivo: {len(df)}")
        print(f"   Linhas puladas (O.S vazia): {pulados}")
        print(f"   Registros CRIADOS: {criados}")
        print(f"   Registros ATUALIZADOS: {atualizados}")
        print(f"   Total processado: {criados + atualizados}")
        print(f"   Com vínculo M10: {com_contrato}")
        print(f"   Sem vínculo M10: {sem_contrato}")
        print(f"   Erros: {erros}")
        print(f"   Valor total: R$ {valor_total:,.2f}")
        
        if pulados > 0:
            print(f"\n⚠️  ATENÇÃO: {pulados} linhas foram puladas por NR_ORDEM vazio/inválido")
        
        if sem_contrato > 0:
            print(f"\n💡 INFO: {sem_contrato} registros salvos sem vínculo M10")
            print(f"   Exemplos de O.S não encontradas: {', '.join(os_nao_encontradas[:5])}")
        
        if erros > 0:
            print(f"\n❌ ERROS ({erros}):")
            for erro in erros_detalhados[:10]:
                print(f"   - {erro}")
            if len(erros_detalhados) > 10:
                print(f"   ... e mais {len(erros_detalhados) - 10} erros")
        
        # Atualizar log
        log.finalizado_em = timezone.now()
        log.calcular_duracao()
        log.total_processadas = criados + atualizados
        log.total_erros = erros
        log.total_contratos_nao_encontrados = sem_contrato
        log.total_valor_importado = valor_total
        log.exemplos_nao_encontrados = ', '.join(os_nao_encontradas[:10]) if os_nao_encontradas else None
        
        if pulados == len(df):
            log.status = 'ERRO'
            log.mensagem_erro = f'Todas as {pulados} linhas foram puladas (NR_ORDEM vazio). Verificar formato do arquivo.'
        elif sem_contrato > 0 and com_contrato == 0:
            log.status = 'PARCIAL'
            log.mensagem_erro = f'{sem_contrato} registros importados sem vínculo M10.'
        elif sem_contrato > 0:
            log.status = 'PARCIAL'
            log.mensagem_erro = f'{com_contrato} com M10, {sem_contrato} sem M10.'
        else:
            log.status = 'SUCESSO'
        
        log.save()
        
        print(f"\n✅ Log ID {log.id} atualizado com status: {log.status}")
        print(f"   Duração: {log.duracao_segundos}s")
        
        # Verificar banco
        print(f"\n🔍 Verificando banco...")
        total_fpd = ImportacaoFPD.objects.count()
        print(f"   Total em ImportacaoFPD: {total_fpd}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERRO CRÍTICO: {str(e)}")
        
        log.status = 'ERRO'
        log.mensagem_erro = str(e)
        log.finalizado_em = timezone.now()
        log.calcular_duracao()
        log.save()
        
        import traceback
        traceback.print_exc()
        
        return False


if __name__ == '__main__':
    print("\n🚀 IMPORTADOR FPD - SELEÇÃO GRÁFICA")
    print("=" * 100)
    
    # Criar janela invisível
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    # Abrir diálogo de arquivo
    print("\n📁 Abrindo seletor de arquivo...")
    print("   (Uma janela de seleção vai abrir)")
    
    arquivo = filedialog.askopenfilename(
        title="Selecione o arquivo FPD para importar",
        filetypes=[
            ("Arquivos Excel", "*.xlsb *.xlsx *.xls"),
            ("Todos os arquivos", "*.*")
        ]
    )
    
    root.destroy()
    
    if not arquivo:
        print("\n❌ Nenhum arquivo selecionado!")
        exit(0)
    
    print(f"\n✅ Arquivo selecionado: {arquivo}")
    
    # Pedir ID do usuário (opcional)
    print("\n👤 Digite o ID do usuário (ou ENTER para pular): ")
    usuario_id_str = input("ID do usuário: ").strip()
    usuario_id = int(usuario_id_str) if usuario_id_str else None
    
    # Confirmar
    print(f"\n⚠️  Você vai importar:")
    print(f"   Arquivo: {arquivo}")
    print(f"   Usuário: {usuario_id or 'Nenhum'}")
    
    confirma = input("\n   Continuar? (s/n): ").strip().lower()
    
    if confirma != 's':
        print("\n❌ Operação cancelada!")
        exit(0)
    
    # Importar
    sucesso = importar_fpd_terminal(arquivo, usuario_id)
    
    if sucesso:
        print("\n" + "=" * 100)
        print("🎉 IMPORTAÇÃO CONCLUÍDA COM SUCESSO!")
        print("=" * 100)
    else:
        print("\n" + "=" * 100)
        print("❌ IMPORTAÇÃO FALHOU!")
        print("=" * 100)
