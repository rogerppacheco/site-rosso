"""
Rebusca os 26 contratos que tiveram dados incompletos
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
from crm_app.services_nio import buscar_todas_faturas_nio_por_cpf

# Lista dos 26 contratos com dados incompletos
contratos_rebuscar = [
    ('07864522', '09980139609'),
    ('07865167', '24167037653'),
    ('07885389', '19123347635'),
    ('07886922', '04764103630'),
    ('07886858', '93317050691'),
    ('07889194', '64027228634'),
    ('07889535', '00052038645'),
    ('07834923', '05707853677'),
    ('07861930', '10123290627'),
    ('07864406', '07615077605'),
    ('07881074', '01291193688'),
    ('07831804', '11348968609'),
    ('07831920', '10968829603'),
    ('07835244', '02982893610'),
    ('07860952', '07003714680'),
    ('07859734', '01270226692'),
    ('07861947', '71042210697'),
    ('07862010', '03207754633'),
    ('07862168', '06853087650'),
    ('07834220', '06836526679'),
    ('07831887', '14190906677'),
    ('07838327', '06990084698'),
    ('07865159', '05894158605'),
    ('07885350', '70444455620'),
    ('07886915', '10883670686'),
    ('07888836', '70353620649'),
]

def rebuscar_contratos():
    print("\n" + "="*80)
    print("REBUSCA DE FATURAS - 26 CONTRATOS COM DADOS INCOMPLETOS")
    print("="*80 + "\n")
    
    hoje = date.today()
    sucessos = []
    erros = []
    
    for idx, (num_contrato, cpf) in enumerate(contratos_rebuscar, 1):
        print(f"\n[{idx}/26] Contrato: {num_contrato} | CPF: {cpf}")
        
        try:
            # Buscar contrato
            contrato = ContratoM10.objects.get(numero_contrato=num_contrato)
            print(f"  Cliente: {contrato.cliente_nome}")
            
            # Buscar faturas pendentes disponíveis
            faturas = FaturaM10.objects.filter(
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
            
            faturas = faturas.order_by('numero_fatura')
            print(f"  Faturas pendentes: {faturas.count()}")
            
            # Buscar no Nio
            print(f"  🔍 Buscando todas as faturas no Nio...")
            faturas_nio = buscar_todas_faturas_nio_por_cpf(cpf, incluir_pdf=False)
            
            if not faturas_nio:
                print(f"  ❌ Nenhuma fatura encontrada na Nio")
                erros.append({
                    'contrato': num_contrato,
                    'erro': 'Nenhuma fatura retornada pela API'
                })
                continue
            
            print(f"  ✅ {len(faturas_nio)} fatura(s) encontrada(s) na Nio")
            
            # Tentar fazer match com vencimento
            atualizadas = 0
            for fatura in faturas:
                melhor_match = None
                menor_diff = 999
                
                for fatura_nio in faturas_nio:
                    if fatura_nio.get('data_vencimento') and fatura.data_vencimento:
                        diff_dias = abs((fatura.data_vencimento - fatura_nio['data_vencimento']).days)
                        if diff_dias <= 3 and diff_dias < menor_diff:
                            menor_diff = diff_dias
                            melhor_match = fatura_nio
                
                if melhor_match:
                    # Atualizar fatura
                    updated = False
                    if melhor_match.get('valor') and fatura.valor != melhor_match['valor']:
                        fatura.valor = melhor_match['valor']
                        updated = True
                    if melhor_match.get('data_vencimento') and fatura.data_vencimento != melhor_match['data_vencimento']:
                        fatura.data_vencimento = melhor_match['data_vencimento']
                        updated = True
                    if melhor_match.get('codigo_pix'):
                        fatura.codigo_pix = melhor_match['codigo_pix']
                        updated = True
                    if melhor_match.get('codigo_barras'):
                        fatura.codigo_barras = melhor_match['codigo_barras']
                        updated = True
                    if melhor_match.get('pdf_url'):
                        fatura.pdf_url = melhor_match['pdf_url']
                        updated = True
                    
                    if updated:
                        fatura.save()
                        print(f"    ✅ Fatura {fatura.numero_fatura}: R$ {melhor_match.get('valor', 0):.2f} - Venc: {melhor_match.get('data_vencimento')}")
                        atualizadas += 1
                    else:
                        print(f"    ℹ️  Fatura {fatura.numero_fatura}: Já estava atualizada")
                else:
                    print(f"    ⚠️  Fatura {fatura.numero_fatura}: Sem match de vencimento")
            
            if atualizadas > 0:
                sucessos.append({
                    'contrato': num_contrato,
                    'cliente': contrato.cliente_nome,
                    'faturas_atualizadas': atualizadas
                })
                print(f"  ✅ {atualizadas} fatura(s) atualizada(s) com sucesso!")
            else:
                erros.append({
                    'contrato': num_contrato,
                    'erro': 'Nenhuma fatura precisou ser atualizada'
                })
        
        except ContratoM10.DoesNotExist:
            print(f"  ❌ Contrato não encontrado no banco")
            erros.append({
                'contrato': num_contrato,
                'erro': 'Contrato não existe'
            })
        except Exception as e:
            print(f"  ❌ Erro: {str(e)}")
            erros.append({
                'contrato': num_contrato,
                'erro': str(e)
            })
    
    # Resumo
    print("\n" + "="*80)
    print("📊 RESUMO DA REBUSCA\n")
    print(f"✅ Sucessos: {len(sucessos)}")
    print(f"❌ Erros: {len(erros)}\n")
    
    if sucessos:
        print("CONTRATOS ATUALIZADOS:")
        for item in sucessos:
            print(f"  • {item['contrato']} - {item['cliente']}: {item['faturas_atualizadas']} fatura(s)")
    
    if erros:
        print("\nERROS:")
        for item in erros:
            print(f"  • {item['contrato']}: {item['erro']}")
    
    print("\n" + "="*80)

if __name__ == '__main__':
    rebuscar_contratos()
