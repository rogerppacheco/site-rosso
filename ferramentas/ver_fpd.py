# Script para verificar dados FPD
# Execute com: python manage.py shell < ver_fpd.py

from crm_app.models import ImportacaoFPD, FaturaM10
from django.db.models import Count, Sum

print("\n" + "="*70)
print(" "*20 + "DADOS FPD NO BANCO")
print("="*70 + "\n")

total_fpd = ImportacaoFPD.objects.count()
total_faturas_fpd = FaturaM10.objects.filter(id_contrato_fpd__isnull=False).count()

print(f"Total de registros ImportacaoFPD: {total_fpd}")
print(f"Total de FaturaM10 com dados FPD: {total_faturas_fpd}")

if total_fpd == 0:
    print("\n⚠️  NENHUM DADO FPD ENCONTRADO")
    print("\n💡 Como importar dados FPD:")
    print("   1. Prepare arquivo Excel/CSV com as colunas:")
    print("      - NR_ORDEM")
    print("      - ID_CONTRATO")
    print("      - NR_FATURA")
    print("      - DT_VENC_ORIG")
    print("      - DT_PAGAMENTO")
    print("      - DS_STATUS_FATURA")
    print("      - VL_FATURA")
    print("      - NR_DIAS_ATRASO")
    print("\n   2. Faça POST para:")
    print("      /api/bonus-m10/importar-fpd/")
    print("\n   3. Ou acesse:")
    print("      http://localhost:8000/importar-fpd/")
else:
    print("\n" + "-"*70)
    print("ESTATÍSTICAS POR STATUS")
    print("-"*70)
    
    for stat in ImportacaoFPD.objects.values('ds_status_fatura').annotate(
        total=Count('id'), valor=Sum('vl_fatura')
    ).order_by('-total'):
        print(f"{stat['ds_status_fatura']:20} | {stat['total']:5} faturas | R$ {stat['valor']:12,.2f}")
    
    print("\n" + "-"*70)
    print("ÚLTIMAS 10 IMPORTAÇÕES")
    print("-"*70)
    
    for i in ImportacaoFPD.objects.order_by('-importada_em')[:10]:
        print(f"{i.nr_ordem:15} | {i.nr_fatura:12} | {i.ds_status_fatura:15} | R$ {i.vl_fatura:10,.2f}")

print("\n" + "="*70)
print("FORMAS DE ACESSAR OS DADOS")
print("="*70)
print("\n1. Admin Django:")
print("   http://localhost:8000/admin/crm_app/importacaofpd/")
print("\n2. API - Buscar por O.S:")
print("   GET /api/bonus-m10/dados-fpd/?os=NR_ORDEM")
print("\n3. API - Listar todas:")
print("   GET /api/bonus-m10/importacoes-fpd/")
print("\n4. API - Filtrar:")
print("   GET /api/bonus-m10/importacoes-fpd/?status=PAGO&mes=2025-01")
print("\n" + "="*70 + "\n")
