"""
Script para vincular dados FPD já importados aos contratos M10
Útil quando FPD foi importado sem encontrar contratos M10
"""

import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10, FaturaM10
from django.utils import timezone
import pandas as pd

def fazer_matching():
    """Vincula ImportacaoFPD a ContratoM10 pelos números de O.S"""
    
    # Busca registros FPD sem vínculo
    fpd_sem_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=True)
    
    print(f"📊 Registros FPD sem vínculo: {fpd_sem_vinculo.count()}")
    print("-" * 80)
    
    vinculados = 0
    nao_encontrados = 0
    erros = []
    
    for fpd in fpd_sem_vinculo:
        try:
            nr_ordem = str(fpd.nr_ordem).strip()
            
            # Tenta encontrar contrato com variações
            variacoes = [
                nr_ordem,
                nr_ordem.lstrip('0'),  # Remove zeros à esquerda
                f'OS-{nr_ordem}',      # Com prefixo
                f'OS-{nr_ordem.lstrip("0")}',
            ]
            
            contrato = None
            for variacao in variacoes:
                try:
                    contrato = ContratoM10.objects.get(ordem_servico=variacao)
                    print(f"✅ O.S {nr_ordem} encontrada em variação: {variacao}")
                    break
                except ContratoM10.DoesNotExist:
                    continue
            
            if contrato:
                # Atualiza FPD com vínculo
                fpd.contrato_m10 = contrato
                fpd.save()
                
                # Cria/atualiza fatura M10 também
                dt_venc_date = fpd.dt_venc_orig
                dt_pgto_date = fpd.dt_pagamento
                vl_fatura_float = float(fpd.vl_fatura) if fpd.vl_fatura else 0
                nr_dias_atraso_int = fpd.nr_dias_atraso
                
                # Mapeia status
                status_map = {
                    'PAGO': 'PAGO',
                    'QUITADO': 'PAGO',
                    'ABERTO': 'NAO_PAGO',
                    'VENCIDO': 'ATRASADO',
                    'AGUARDANDO': 'AGUARDANDO',
                }
                status_str = str(fpd.ds_status_fatura).upper()
                status = status_map.get(status_str, 'NAO_PAGO')
                
                # Cria/atualiza fatura
                fatura, created = FaturaM10.objects.update_or_create(
                    contrato=contrato,
                    numero_fatura=1,
                    defaults={
                        'numero_fatura_operadora': fpd.nr_fatura,
                        'valor': Decimal(str(vl_fatura_float)),
                        'data_vencimento': dt_venc_date,
                        'data_pagamento': dt_pgto_date,
                        'dias_atraso': nr_dias_atraso_int,
                        'status': status,
                        'id_contrato_fpd': fpd.id_contrato,
                        'dt_pagamento_fpd': dt_pgto_date,
                        'ds_status_fatura_fpd': status_str,
                        'data_importacao_fpd': timezone.now(),
                    }
                )
                
                vinculados += 1
                print(f"   └─ Fatura criada/atualizada (contrato ID: {contrato.id})")
            else:
                nao_encontrados += 1
                print(f"❌ O.S {nr_ordem} ainda não encontrada em ContratoM10")
                
        except Exception as e:
            erros.append(f"O.S {fpd.nr_ordem}: {str(e)}")
            print(f"⚠️  Erro ao processar O.S {fpd.nr_ordem}: {str(e)}")
    
    print("\n" + "=" * 80)
    print(f"✅ Vinculados: {vinculados}")
    print(f"❌ Não encontrados: {nao_encontrados}")
    print(f"⚠️  Erros: {len(erros)}")
    
    if erros:
        print("\n📋 Erros detalhados:")
        for erro in erros[:10]:
            print(f"   - {erro}")
        if len(erros) > 10:
            print(f"   ... e mais {len(erros) - 10} erros")
    
    print("\n💡 Próximos passos:")
    if nao_encontrados > 0:
        print(f"   1. Importar os {nao_encontrados} contratos M10 faltantes")
        print("   2. Rodar este script novamente")
    else:
        print("   ✅ Todos os registros FPD foram vinculados com sucesso!")


def buscar_os_nao_encontradas():
    """Lista as O.S que ainda não foram encontradas"""
    fpd_sem_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=True)
    
    print("\n📋 O.S ainda não encontradas em ContratoM10:\n")
    
    os_list = fpd_sem_vinculo.values_list('nr_ordem', flat=True).distinct()
    
    for i, os in enumerate(os_list, 1):
        count = fpd_sem_vinculo.filter(nr_ordem=os).count()
        print(f"{i:3d}. O.S {os:<15} ({count} fatura(s))")
    
    print(f"\nTotal: {len(os_list)} O.S distintas para vincular")
    
    return list(os_list)


if __name__ == '__main__':
    print("🔗 Matching FPD ↔ ContratoM10")
    print("=" * 80)
    
    fazer_matching()
    
    print("\n" + "=" * 80)
    print("Deseja listar as O.S ainda não encontradas? (S/N): ", end="")
    resposta = input().strip().upper()
    
    if resposta == 'S':
        os_nao_encontradas = buscar_os_nao_encontradas()
        
        print("\n💾 Salvando lista em CSV...")
        df = pd.DataFrame({'NR_ORDEM': os_nao_encontradas})
        df.to_csv('os_nao_encontradas.csv', index=False)
        print("   └─ Arquivo: os_nao_encontradas.csv")
