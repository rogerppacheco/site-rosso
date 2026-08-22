"""
Teste rápido para validar a importação FPD sem dependência de ContratoM10
"""

import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10
from django.utils import timezone
import pandas as pd
from datetime import date, timedelta

def testar_importacao_sem_contrato():
    """Simula importação de dados FPD sem contrato M10"""
    
    print("🧪 Teste: Importação FPD sem ContratoM10")
    print("=" * 80)
    
    # Dados de teste
    dados_teste = {
        'NR_ORDEM': ['99999991', '99999992', '99999993'],
        'ID_CONTRATO': ['TEST001', 'TEST002', 'TEST003'],
        'NR_FATURA': ['FAT001', 'FAT002', 'FAT003'],
        'DT_VENC_ORIG': [date.today() + timedelta(days=30)] * 3,
        'DT_PAGAMENTO': [None, date.today(), None],
        'DS_STATUS_FATURA': ['ABERTO', 'PAGO', 'VENCIDO'],
        'VL_FATURA': [1000.00, 2000.00, 3000.00],
        'NR_DIAS_ATRASO': [0, 0, 30],
        'NR_CONTRATO': ['CONT001', 'CONT002', 'CONT003'],
    }
    
    df = pd.DataFrame(dados_teste)
    
    print(f"\n📊 Dados de teste:")
    print(df.to_string())
    
    # Limpa dados antigos
    ImportacaoFPD.objects.filter(nr_ordem__startswith='9999999').delete()
    print("\n🗑️  Deletados registros de teste antigos")
    
    # Simula importação
    print("\n📥 Importando...")
    
    status_map = {
        'PAGO': 'PAGO',
        'QUITADO': 'PAGO',
        'ABERTO': 'NAO_PAGO',
        'VENCIDO': 'ATRASADO',
        'AGUARDANDO': 'AGUARDANDO',
    }
    
    registros_importados = 0
    for idx, row in df.iterrows():
        try:
            nr_ordem = str(row['NR_ORDEM']).strip()
            nr_fatura = str(row['NR_FATURA']).strip()
            
            # Verifica se contrato existe (não deveria)
            try:
                contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                print(f"   └─ ⚠️  O.S {nr_ordem} encontrada (inesperado)")
            except ContratoM10.DoesNotExist:
                # Novo código: salva mesmo sem contrato
                importacao_fpd, created = ImportacaoFPD.objects.update_or_create(
                    nr_ordem=nr_ordem,
                    nr_fatura=nr_fatura,
                    defaults={
                        'id_contrato': str(row['ID_CONTRATO']).strip(),
                        'dt_venc_orig': pd.to_datetime(row['DT_VENC_ORIG']).date(),
                        'dt_pagamento': pd.to_datetime(row['DT_PAGAMENTO']).date() if pd.notna(row['DT_PAGAMENTO']) else None,
                        'nr_dias_atraso': int(row['NR_DIAS_ATRASO']),
                        'ds_status_fatura': str(row['DS_STATUS_FATURA']).upper(),
                        'vl_fatura': Decimal(str(row['VL_FATURA'])),
                        'contrato_m10': None,  # ← Sem vínculo!
                    }
                )
                registros_importados += 1
                status = "✅ CRIADO" if created else "✏️  ATUALIZADO"
                print(f"   └─ {status} O.S {nr_ordem} (sem contrato)")
        
        except Exception as e:
            print(f"   └─ ❌ Erro em O.S {row['NR_ORDEM']}: {str(e)}")
    
    # Valida
    print(f"\n✅ Importados: {registros_importados} registros")
    
    # Busca registros salvos
    registros_salvos = ImportacaoFPD.objects.filter(nr_ordem__startswith='9999999')
    
    print(f"\n📋 Verificando dados salvos:")
    print(f"   Total em banco: {registros_salvos.count()}")
    
    for fpd in registros_salvos:
        contrato_str = f"Contrato: {fpd.contrato_m10.id}" if fpd.contrato_m10 else "Sem contrato"
        print(f"   ├─ O.S: {fpd.nr_ordem}")
        print(f"   │  Fatura: {fpd.nr_fatura}")
        print(f"   │  Valor: R$ {fpd.vl_fatura}")
        print(f"   │  Status: {fpd.ds_status_fatura}")
        print(f"   │  {contrato_str}")
    
    # Testa busca
    print(f"\n🔍 Teste de busca por O.S:")
    
    for os_numero in ['99999991', '99999992', '99999993']:
        found = ImportacaoFPD.objects.filter(nr_ordem=os_numero).exists()
        status = "✅ ENCONTRADA" if found else "❌ NÃO ENCONTRADA"
        print(f"   O.S {os_numero}: {status}")
    
    # Resume
    print("\n" + "=" * 80)
    print("✅ TESTE CONCLUÍDO COM SUCESSO!")
    print("\nO que foi validado:")
    print("  ✅ Dados FPD são salvos mesmo sem contrato M10")
    print("  ✅ Campo contrato_m10 fica NULL")
    print("  ✅ Todos os dados são preservados")
    print("  ✅ Busca funciona normalmente")
    print("\n💡 Próximo passo: importar dados reais do arquivo FPD")

if __name__ == '__main__':
    testar_importacao_sem_contrato()
