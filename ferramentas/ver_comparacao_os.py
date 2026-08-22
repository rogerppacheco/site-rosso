"""
Script para comparar O.S entre arquivo FPD e banco CRM
Identifica matches e não-matches para diagnóstico
"""
import os
import django
import pandas as pd
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10

def main():
    print("=" * 80)
    print("COMPARAÇÃO DE ORDENS DE SERVIÇO - FPD vs CRM")
    print("=" * 80)
    print()
    
    # Solicitar caminho do arquivo
    arquivo_fpd = input("Digite o caminho completo do arquivo FPD (ou Enter para usar '1067098.xlsb'): ").strip()
    if not arquivo_fpd:
        arquivo_fpd = '1067098.xlsb'
    
    # Verificar se arquivo existe
    if not Path(arquivo_fpd).exists():
        print(f"❌ ERRO: Arquivo '{arquivo_fpd}' não encontrado!")
        print(f"   Caminho atual: {os.getcwd()}")
        print(f"   Arquivos disponíveis neste diretório:")
        for f in Path('.').glob('*.xls*'):
            print(f"     • {f.name}")
        return
    
    # Ler arquivo FPD
    print(f"📄 Lendo arquivo: {arquivo_fpd}")
    try:
        if arquivo_fpd.endswith('.xlsb'):
            df = pd.read_excel(arquivo_fpd, engine='pyxlsb')
        else:
            df = pd.read_excel(arquivo_fpd)
    except Exception as e:
        print(f"❌ Erro ao ler arquivo: {e}")
        return
    
    print(f"   ✅ Arquivo lido com sucesso!")
    print(f"   📊 Total de linhas: {len(df)}")
    print()
    
    # Verificar se coluna nr_ordem existe
    if 'nr_ordem' not in df.columns:
        print(f"❌ ERRO: Coluna 'nr_ordem' não encontrada!")
        print(f"   Colunas disponíveis: {df.columns.tolist()}")
        return
    
    # Extrair O.S únicas do FPD
    os_fpd = df['nr_ordem'].astype(str).str.strip().unique()
    os_fpd = [os for os in os_fpd if os and os != 'nan']  # Remover vazios
    
    print(f"📄 ARQUIVO FPD:")
    print(f"   Total O.S únicas: {len(os_fpd)}")
    print(f"   Primeiras 10:")
    for i, os in enumerate(os_fpd[:10], 1):
        print(f"      {i:2d}. '{os}'")
    print()
    
    # Buscar O.S no banco CRM
    print(f"🏢 BANCO CRM (ContratoM10):")
    total_contratos = ContratoM10.objects.count()
    contratos_com_os = ContratoM10.objects.exclude(
        ordem_servico__isnull=True
    ).exclude(
        ordem_servico=''
    )
    
    print(f"   Total contratos: {total_contratos}")
    print(f"   Com O.S preenchida: {contratos_com_os.count()}")
    
    if contratos_com_os.count() == 0:
        print()
        print("❌ PROBLEMA CRÍTICO IDENTIFICADO!")
        print("   Nenhum contrato M10 tem o campo 'ordem_servico' preenchido!")
        print()
        print("💡 SOLUÇÃO:")
        print("   1. Verifique a importação dos contratos M10")
        print("   2. Certifique-se que o campo 'ordem_servico' está sendo preenchido")
        print("   3. Se necessário, atualize os contratos existentes com O.S")
        print("   4. Depois reimporte o arquivo FPD")
        return
    
    os_crm = list(contratos_com_os.values_list('ordem_servico', flat=True))
    
    print(f"   Primeiras 10:")
    for i, os in enumerate(os_crm[:10], 1):
        print(f"      {i:2d}. '{os}'")
    print()
    
    # Comparar
    print("=" * 80)
    print("🔍 ANÁLISE DE MATCHING")
    print("=" * 80)
    print()
    
    em_comum = set(os_fpd) & set(os_crm)
    so_fpd = set(os_fpd) - set(os_crm)
    so_crm = set(os_crm) - set(os_fpd)
    
    taxa_match = (len(em_comum) / len(os_fpd) * 100) if len(os_fpd) > 0 else 0
    
    print(f"✅ Em comum (Match Exato): {len(em_comum):,} ({taxa_match:.1f}% do FPD)")
    print(f"❌ Só no FPD: {len(so_fpd):,}")
    print(f"⚠️  Só no CRM: {len(so_crm):,}")
    print()
    
    if len(em_comum) > 0:
        print("=" * 80)
        print("✅ BOAS NOTÍCIAS!")
        print("=" * 80)
        print(f"Foram encontradas {len(em_comum):,} O.S em comum!")
        print()
        print("Exemplos de O.S que PODEM ser importadas:")
        for i, os in enumerate(sorted(em_comum)[:10], 1):
            print(f"   {i:2d}. {os}")
        print()
        print("💡 PRÓXIMOS PASSOS:")
        print("   1. Reimporte o arquivo FPD")
        print("   2. Agora devem ser processados pelo menos", len(em_comum), "registros")
        print("   3. Acesse /validacao-fpd/ para verificar o resultado")
    else:
        print("=" * 80)
        print("❌ PROBLEMA CRÍTICO!")
        print("=" * 80)
        print("NENHUMA O.S em comum encontrada!")
        print()
        print("🔍 Análise de Formato:")
        print()
        print("   Exemplo FPD:", f"'{os_fpd[0]}'")
        print("   Exemplo CRM:", f"'{os_crm[0]}'")
        print()
        
        # Tentar identificar padrão
        print("🤔 Possíveis causas:")
        print()
        
        # Verificar se FPD tem prefixo OS-
        tem_prefixo_fpd = any('OS-' in str(os).upper() for os in os_fpd[:10])
        tem_prefixo_crm = any('OS-' in str(os).upper() for os in os_crm[:10])
        
        if tem_prefixo_fpd and not tem_prefixo_crm:
            print("   1. ⚠️ FPD tem prefixo 'OS-' mas CRM não tem")
            print("      Solução: Remover prefixo do FPD ou adicionar no CRM")
        elif not tem_prefixo_fpd and tem_prefixo_crm:
            print("   1. ⚠️ CRM tem prefixo 'OS-' mas FPD não tem")
            print("      Solução: Adicionar prefixo no FPD ou remover do CRM")
        else:
            print("   1. ❓ Formato parece similar, mas valores diferentes")
            print("      Solução: Verificar se são bases/períodos diferentes")
        
        print()
        print("   2. 🔢 Possível diferença de dígitos/zeros à esquerda")
        print("      Exemplo: '12345' vs '012345'")
        print()
        print("   3. 📅 Bases podem ser de períodos/sistemas diferentes")
        print("      Exemplo: FPD de 2025, CRM de 2024")
    
    if len(so_fpd) > 0 and len(so_fpd) < 100:  # Se não for muitas, mostrar todas
        print()
        print("=" * 80)
        print(f"❌ O.S QUE NÃO SERÃO IMPORTADAS ({len(so_fpd)} total)")
        print("=" * 80)
        print()
        print("Primeiras 50 O.S que falharam:")
        for i, os in enumerate(sorted(so_fpd)[:50], 1):
            print(f"   {i:2d}. {os}")
        
        if len(so_fpd) > 50:
            print(f"   ... e mais {len(so_fpd) - 50}")
    
    print()
    print("=" * 80)
    print("💾 SALVANDO RESULTADOS")
    print("=" * 80)
    
    # Salvar relatório em arquivo
    with open('relatorio_comparacao_os.txt', 'w', encoding='utf-8') as f:
        f.write("RELATÓRIO DE COMPARAÇÃO - FPD vs CRM\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Arquivo FPD: {arquivo_fpd}\n")
        f.write(f"Data: {pd.Timestamp.now()}\n\n")
        f.write(f"Total O.S no FPD: {len(os_fpd):,}\n")
        f.write(f"Total O.S no CRM: {len(os_crm):,}\n")
        f.write(f"Em comum: {len(em_comum):,} ({taxa_match:.1f}%)\n")
        f.write(f"Só no FPD: {len(so_fpd):,}\n")
        f.write(f"Só no CRM: {len(so_crm):,}\n\n")
        
        if len(em_comum) > 0:
            f.write("O.S EM COMUM:\n")
            for os in sorted(em_comum):
                f.write(f"  {os}\n")
            f.write("\n")
        
        if len(so_fpd) > 0:
            f.write("O.S SÓ NO FPD (NÃO IMPORTADAS):\n")
            for os in sorted(so_fpd):
                f.write(f"  {os}\n")
    
    print("   ✅ Relatório salvo em: relatorio_comparacao_os.txt")
    print()
    print("=" * 80)
    print("FIM DA ANÁLISE")
    print("=" * 80)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Operação cancelada pelo usuário")
    except Exception as e:
        print(f"\n\n❌ ERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
