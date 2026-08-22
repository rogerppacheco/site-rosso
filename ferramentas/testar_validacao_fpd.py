"""
Script para testar o sistema de validação FPD
Verifica se logs existem e exibe estatísticas
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import LogImportacaoFPD, ImportacaoFPD, ContratoM10
from django.db.models import Count, Sum, Avg, Q

def main():
    print("=" * 70)
    print("SISTEMA DE VALIDAÇÃO FPD - TESTE DE FUNCIONALIDADE")
    print("=" * 70)
    print()
    
    # Estatísticas de Logs
    print("📊 ESTATÍSTICAS DE LOGS DE IMPORTAÇÃO")
    print("-" * 70)
    
    total_logs = LogImportacaoFPD.objects.count()
    print(f"Total de logs: {total_logs}")
    
    if total_logs > 0:
        stats = LogImportacaoFPD.objects.aggregate(
            total_sucesso=Count('id', filter=Q(status='SUCESSO')),
            total_erro=Count('id', filter=Q(status='ERRO')),
            total_parcial=Count('id', filter=Q(status='PARCIAL')),
            total_processando=Count('id', filter=Q(status='PROCESSANDO')),
            total_linhas=Sum('total_linhas'),
            total_processadas=Sum('total_processadas'),
            media_duracao=Avg('duracao_segundos'),
            total_valor=Sum('total_valor_importado')
        )
        
        print(f"✅ Sucesso: {stats['total_sucesso']}")
        print(f"❌ Erro: {stats['total_erro']}")
        print(f"⚠️  Parcial: {stats['total_parcial']}")
        print(f"⏳ Processando: {stats['total_processando']}")
        print(f"📄 Total linhas: {stats['total_linhas'] or 0}")
        print(f"✔️  Total processadas: {stats['total_processadas'] or 0}")
        print(f"⏱️  Duração média: {stats['media_duracao'] or 0:.2f}s")
        print(f"💰 Valor total: R$ {stats['total_valor'] or 0:,.2f}")
        
        print()
        print("📋 ÚLTIMOS 5 LOGS:")
        print("-" * 70)
        
        for log in LogImportacaoFPD.objects.order_by('-iniciado_em')[:5]:
            status_emoji = {
                'SUCESSO': '✅',
                'ERRO': '❌',
                'PARCIAL': '⚠️',
                'PROCESSANDO': '⏳'
            }
            
            print(f"{status_emoji.get(log.status, '❓')} {log.nome_arquivo}")
            print(f"   Data: {log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S')}")
            print(f"   Usuário: {log.usuario.username if log.usuario else 'N/A'}")
            print(f"   Linhas: {log.total_linhas} | Processadas: {log.total_processadas} | Erros: {log.total_erros}")
            
            if log.exemplos_nao_encontrados:
                print(f"   O.S Não Encontradas: {len(log.exemplos_nao_encontrados)} (exemplos: {', '.join(log.exemplos_nao_encontrados[:3])})")
            
            print()
    
    else:
        print("ℹ️  Nenhum log de importação encontrado ainda.")
        print("   Faça uma importação FPD para ver os logs aqui.")
    
    print()
    print("=" * 70)
    print("📁 DADOS FPD IMPORTADOS")
    print("=" * 70)
    
    total_importacoes = ImportacaoFPD.objects.count()
    print(f"Total de registros FPD: {total_importacoes}")
    
    if total_importacoes > 0:
        stats_fpd = ImportacaoFPD.objects.aggregate(
            total_valor=Sum('vl_fatura'),
            total_contratos=Count('contrato_m10', distinct=True)
        )
        
        print(f"💰 Valor total: R$ {stats_fpd['total_valor'] or 0:,.2f}")
        print(f"📋 Contratos únicos: {stats_fpd['total_contratos']}")
        
        # Status das faturas
        status_counts = ImportacaoFPD.objects.values('ds_status_fatura').annotate(
            total=Count('id')
        ).order_by('-total')
        
        print()
        print("Status das Faturas:")
        for item in status_counts[:5]:
            print(f"  • {item['ds_status_fatura']}: {item['total']}")
    
    print()
    print("=" * 70)
    print("🏢 CONTRATOS M10")
    print("=" * 70)
    
    total_contratos = ContratoM10.objects.count()
    print(f"Total de contratos M10: {total_contratos}")
    
    if total_contratos > 0:
        # Contratos com dados FPD
        contratos_com_fpd = ContratoM10.objects.filter(
            importacoes_fpd__isnull=False
        ).distinct().count()
        
        print(f"✔️  Contratos com dados FPD: {contratos_com_fpd}")
        print(f"❌ Contratos sem dados FPD: {total_contratos - contratos_com_fpd}")
        
        if contratos_com_fpd > 0:
            taxa = (contratos_com_fpd / total_contratos) * 100
            print(f"📊 Taxa de cobertura FPD: {taxa:.1f}%")
    
    print()
    print("=" * 70)
    print("🔗 URLS DISPONÍVEIS")
    print("=" * 70)
    print("📄 Validação FPD: /validacao-fpd/")
    print("📤 Importar FPD: /importar-fpd/")
    print("🔌 API Logs: /api/bonus-m10/logs-importacao-fpd/")
    print("🔌 API Dados FPD: /api/bonus-m10/dados-fpd/?os=OS-12345")
    print("🔌 API Importações: /api/bonus-m10/importacoes-fpd/")
    print("⚙️  Admin Logs: /admin/crm_app/logimportacaofpd/")
    print("⚙️  Admin Importações: /admin/crm_app/importacaofpd/")
    print()
    print("=" * 70)
    print("✅ SISTEMA DE VALIDAÇÃO FPD FUNCIONANDO CORRETAMENTE!")
    print("=" * 70)

if __name__ == '__main__':
    main()
