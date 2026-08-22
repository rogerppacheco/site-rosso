"""
Script para importar FPD via terminal com logs completos
Valida registros existentes e atualiza, ou insere novos
"""

import os
import django
import pandas as pd
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10, LogImportacaoFPD
from django.utils import timezone
from usuarios.models import Usuario

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
        
        if arquivo_path.endswith('.csv'):
            df = pd.read_csv(arquivo_path)
        elif arquivo_path.endswith('.xlsb'):
            try:
                df = pd.read_excel(arquivo_path, engine='pyxlsb')
            except Exception as e:
                raise Exception(f'Formato .xlsb não suportado ou erro ao ler: {str(e)}')
        else:
            df = pd.read_excel(arquivo_path)
        
        print(f"✅ Arquivo lido: {len(df)} linhas")
        
        # Mostrar colunas
        print(f"\n📋 Colunas encontradas ({len(df.columns)}):")
        for i, col in enumerate(df.columns, 1):
            print(f"   {i:2d}. {col}")
        
        # Verificar coluna NR_ORDEM
        if 'NR_ORDEM' not in df.columns:
            print(f"\n❌ ERRO: Coluna 'NR_ORDEM' não encontrada!")
            print(f"   Colunas disponíveis: {', '.join(df.columns)}")
            raise Exception("Coluna 'NR_ORDEM' não encontrada no arquivo")
        
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
                # Extrair NR_ORDEM
                nr_ordem_raw = row.get('NR_ORDEM', '')
                nr_ordem = str(nr_ordem_raw).strip()
                
                # Debug primeiras 5 linhas
                if idx < 5:
                    print(f"\n📌 Linha {idx + 1}:")
                    print(f"   NR_ORDEM raw: '{nr_ordem_raw}' (tipo: {type(nr_ordem_raw).__name__})")
                    print(f"   NR_ORDEM processado: '{nr_ordem}'")
                
                # Validar NR_ORDEM
                if not nr_ordem or nr_ordem == 'nan' or nr_ordem.lower() == 'none':
                    if idx < 5:
                        print(f"   ⚠️  PULANDO - NR_ORDEM vazio ou inválido")
                    pulados += 1
                    continue
                
                if idx < 5:
                    print(f"   ✅ NR_ORDEM válida: {nr_ordem}")
                
                # Extrair outros campos
                nr_fatura = str(row.get('NR_FATURA', '')).strip()
                id_contrato = str(row.get('ID_CONTRATO', '')).strip()
                
                # Datas
                dt_venc = row.get('DT_VENC_ORIG')
                dt_venc_date = pd.to_datetime(dt_venc).date() if pd.notna(dt_venc) else timezone.now().date()
                
                dt_pgto = row.get('DT_PAGAMENTO')
                dt_pgto_date = pd.to_datetime(dt_pgto).date() if pd.notna(dt_pgto) else None
                
                # Valores
                vl_fatura = row.get('VL_FATURA', 0)
                vl_fatura_float = float(vl_fatura) if pd.notna(vl_fatura) else 0
                
                nr_dias_atraso = row.get('NR_DIAS_ATRASO', 0)
                nr_dias_atraso_int = int(nr_dias_atraso) if pd.notna(nr_dias_atraso) else 0
                
                # Status
                status_str = str(row.get('DS_STATUS_FATURA', 'NAO_PAGO')).upper()
                
                if idx < 5:
                    print(f"   Fatura: {nr_fatura}")
                    print(f"   Valor: R$ {vl_fatura_float:,.2f}")
                    print(f"   Status: {status_str}")
                
                # Buscar ContratoM10
                contrato = None
                try:
                    contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                    if idx < 5:
                        print(f"   ✅ ContratoM10 encontrado: {contrato.cliente_nome}")
                except ContratoM10.DoesNotExist:
                    if idx < 5:
                        print(f"   ⚠️  ContratoM10 NÃO encontrado")
                
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
                        'ds_status_fatura': status_str,
                        'vl_fatura': Decimal(str(vl_fatura_float)),
                        'contrato_m10': contrato,
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
            print(f"   Execute 'python fazer_matching_fpd_m10.py' para vincular depois")
        
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
    print("\n🚀 IMPORTADOR FPD - TERMINAL")
    print("=" * 100)
    
    # Procurar arquivos Excel na pasta atual
    arquivos_encontrados = []
    pasta_atual = os.getcwd()
    
    print(f"\n📁 Procurando arquivos Excel em: {pasta_atual}")
    
    for arquivo_nome in os.listdir(pasta_atual):
        if arquivo_nome.lower().endswith(('.xlsb', '.xlsx', '.xls', '.csv')):
            caminho_completo = os.path.join(pasta_atual, arquivo_nome)
            tamanho = os.path.getsize(caminho_completo)
            arquivos_encontrados.append((caminho_completo, arquivo_nome, tamanho))
    
    # Se encontrou arquivos
    if arquivos_encontrados:
        print(f"\n✅ {len(arquivos_encontrados)} arquivo(s) encontrado(s):\n")
        for i, (caminho, nome, tamanho) in enumerate(arquivos_encontrados, 1):
            tamanho_mb = tamanho / (1024 * 1024)
            print(f"   {i}. {nome} ({tamanho_mb:.2f} MB)")
        
        print(f"\n   0. Digitar caminho manualmente")
        
        escolha = input(f"\nEscolha um arquivo (0-{len(arquivos_encontrados)}): ").strip()
        
        try:
            numero = int(escolha)
            if 1 <= numero <= len(arquivos_encontrados):
                arquivo = arquivos_encontrados[numero - 1][0]
            elif numero == 0:
                arquivo = input("Digite o caminho completo: ").strip().strip('"').strip("'")
            else:
                print(f"❌ Opção inválida!")
                exit(1)
        except ValueError:
            print(f"❌ Entrada inválida!")
            exit(1)
    else:
        print(f"\n⚠️  Nenhum arquivo Excel encontrado em {pasta_atual}")
        print(f"\n📁 Digite o caminho completo do arquivo FPD:")
        print(f"   Exemplo: D:\\Downloads\\1067098.xlsb")
        arquivo = input("Caminho do arquivo: ").strip().strip('"').strip("'")
    
    # Verificar se existe
    if not os.path.exists(arquivo):
        print(f"\n❌ Arquivo não encontrado: {arquivo}")
        print(f"   Pasta atual: {pasta_atual}")
        exit(1)
    
    print(f"\n✅ Arquivo selecionado: {arquivo}")
    
    # Pedir ID do usuário (opcional)
    print("\n👤 Digite o ID do usuário (ou ENTER para pular): ")
    usuario_id_str = input("ID do usuário: ").strip()
    usuario_id = int(usuario_id_str) if usuario_id_str else None
    
    # Confirmar
    print(f"\n⚠️  Você vai importar:")
    print(f"   Arquivo: {arquivo}")
    print(f"   Usuário: {usuario_id or 'Nenhum'}")
    print(f"\n   ATENÇÃO:")
    print(f"   - Registros existentes serão ATUALIZADOS")
    print(f"   - Registros novos serão CRIADOS")
    print(f"   - Nenhum dado será perdido")
    
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
        print("\n📝 Próximos passos:")
        print("   1. Verificar dados: python verificar_dados_banco.py")
        print("   2. Fazer matching M10: python fazer_matching_fpd_m10.py")
        print("   3. Validar integridade: python limpar_e_validar_fpd.py")
    else:
        print("\n" + "=" * 100)
        print("❌ IMPORTAÇÃO FALHOU!")
        print("=" * 100)
        print("\n   Verifique os erros acima e tente novamente.")
