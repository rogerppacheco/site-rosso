"""
Analisa erros da última execução de busca automática de faturas
"""
import sys
import os
import django

# Configurar Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from datetime import date
from crm_app.models import ContratoM10, FaturaM10
from crm_app.services_nio import buscar_fatura_nio_por_cpf

def analisar_erros():
    """
    Identifica quais faturas tiveram erro na última busca
    """
    print("\n" + "="*80)
    print("ANALISE DE ERROS - BUSCA AUTOMATICA DE FATURAS")
    print("="*80 + "\n")
    
    hoje = date.today()
    erros_encontrados = []
    
    # Buscar contratos ativos
    contratos = ContratoM10.objects.filter(status_contrato='ATIVO').select_related('vendedor')
    total_contratos = contratos.count()
    
    print(f"Analisando {total_contratos} contratos ativos...\n")
    
    for idx, contrato in enumerate(contratos, 1):
        if not contrato.cpf_cliente:
            continue
        
        # Buscar faturas pendentes disponíveis
        faturas_pendentes = FaturaM10.objects.filter(
            contrato=contrato,
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
        ).filter(
            data_disponibilidade__isnull=False,
            data_disponibilidade__lte=hoje
        ) | FaturaM10.objects.filter(
            contrato=contrato,
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO'],
            data_disponibilidade__isnull=True
        )
        
        if not faturas_pendentes.exists():
            continue
        
        # Verificar cada fatura
        for fatura in faturas_pendentes:
            # Se tem data de vencimento mas não tem PIX/código de barras = erro
            if fatura.data_vencimento and not fatura.codigo_pix and not fatura.codigo_barras:
                try:
                    # Tentar buscar novamente para ver o erro
                    dados = buscar_fatura_nio_por_cpf(contrato.cpf_cliente)
                    
                    if not dados or dados.get('sem_dividas'):
                        erro_tipo = 'API_SEM_DADOS'
                        erro_msg = dados.get('mensagem', 'API retornou sem dados') if dados else 'Falha na requisição'
                    else:
                        erro_tipo = 'DADOS_INCOMPLETOS'
                        erro_msg = f"Dados retornados: PIX={bool(dados.get('codigo_pix'))}, Barras={bool(dados.get('codigo_barras'))}"
                except Exception as e:
                    erro_tipo = 'EXCEPTION'
                    erro_msg = str(e)
                
                erros_encontrados.append({
                    'contrato': contrato.numero_contrato,
                    'cliente': contrato.cliente_nome,
                    'cpf': contrato.cpf_cliente,
                    'fatura': fatura.numero_fatura,
                    'vencimento': fatura.data_vencimento.strftime('%d/%m/%Y') if fatura.data_vencimento else 'N/A',
                    'tipo': erro_tipo,
                    'erro': erro_msg
                })
                
        if idx % 50 == 0:
            print(f"  Processados: {idx}/{total_contratos}...")
    
    # Exibir resultados
    print(f"\n{len(erros_encontrados)} erro(s) identificado(s):\n")
    print("="*80)
    
    if erros_encontrados:
        # Agrupar por tipo
        erros_por_tipo = {}
        for erro in erros_encontrados:
            tipo = erro['tipo']
            if tipo not in erros_por_tipo:
                erros_por_tipo[tipo] = []
            erros_por_tipo[tipo].append(erro)
        
        # Exibir agrupados
        for tipo, erros in erros_por_tipo.items():
            print(f"\n[{tipo}] - {len(erros)} caso(s):\n")
            for erro in erros[:10]:  # Limitar a 10 primeiros de cada tipo
                print(f"  Contrato: {erro['contrato']}")
                print(f"  Cliente: {erro['cliente']}")
                print(f"  CPF: {erro['cpf']}")
                print(f"  Fatura: {erro['fatura']} (Venc: {erro['vencimento']})")
                print(f"  Erro: {erro['erro']}")
                print()
            
            if len(erros) > 10:
                print(f"  ... e mais {len(erros) - 10} erro(s) deste tipo\n")
        
        # Salvar em arquivo
        with open('erros_detalhados.txt', 'w', encoding='utf-8') as f:
            f.write("ERROS DETALHADOS - BUSCA AUTOMATICA DE FATURAS\n")
            f.write("="*80 + "\n\n")
            
            for tipo, erros in erros_por_tipo.items():
                f.write(f"\n[{tipo}] - {len(erros)} caso(s):\n\n")
                for erro in erros:
                    f.write(f"Contrato: {erro['contrato']}\n")
                    f.write(f"Cliente: {erro['cliente']}\n")
                    f.write(f"CPF: {erro['cpf']}\n")
                    f.write(f"Fatura: {erro['fatura']} (Venc: {erro['vencimento']})\n")
                    f.write(f"Erro: {erro['erro']}\n")
                    f.write("-" * 80 + "\n\n")
        
        print(f"\nArquivo 'erros_detalhados.txt' criado com todos os {len(erros_encontrados)} erros.")
    else:
        print("Nenhum erro identificado!")
    
    print("\n" + "="*80)

if __name__ == '__main__':
    analisar_erros()
