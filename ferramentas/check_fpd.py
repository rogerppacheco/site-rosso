from crm_app.models import ImportacaoFPD, FaturaM10
from django.db.models import Count, Sum

print("\n" + "="*60)
print("  DADOS FPD ATUALMENTE NO BANCO")
print("="*60 + "\n")

# Contar registros
total_importacoes = ImportacaoFPD.objects.count()
total_faturas_fpd = FaturaM10.objects.filter(id_contrato_fpd__isnull=False).count()

print(f"📊 Total ImportacaoFPD: {total_importacoes} registros")
print(f"📊 Total FaturaM10 com dados FPD: {total_faturas_fpd} registros")

if total_importacoes > 0:
    print("\n" + "-"*60)
    print("  ESTATÍSTICAS POR STATUS")
    print("-"*60)
    
    stats = ImportacaoFPD.objects.values('ds_status_fatura').annotate(
        total=Count('id'),
        valor_total=Sum('vl_fatura')
    ).order_by('-total')
    
    for stat in stats:
        status = stat['ds_status_fatura']
        total = stat['total']
        valor = stat['valor_total'] or 0
        print(f"  {status:20} → {total:4} faturas → R$ {valor:,.2f}")
    
    print("\n" + "-"*60)
    print("  ÚLTIMAS 10 IMPORTAÇÕES")
    print("-"*60)
    
    for imp in ImportacaoFPD.objects.order_by('-importada_em')[:10]:
        print(f"  O.S: {imp.nr_ordem:15} | Fatura: {imp.nr_fatura:10} | Status: {imp.ds_status_fatura:15} | R$ {imp.vl_fatura:8,.2f} | {imp.importada_em.strftime('%d/%m/%Y %H:%M')}")
    
    print("\n" + "-"*60)
    print("  PRIMEIRAS 5 IMPORTAÇÕES")
    print("-"*60)
    
    for imp in ImportacaoFPD.objects.order_by('importada_em')[:5]:
        print(f"  O.S: {imp.nr_ordem:15} | Fatura: {imp.nr_fatura:10} | Status: {imp.ds_status_fatura:15} | R$ {imp.vl_fatura:8,.2f} | {imp.importada_em.strftime('%d/%m/%Y %H:%M')}")
        
    # Estatísticas gerais
    total_valor = ImportacaoFPD.objects.aggregate(Sum('vl_fatura'))['vl_fatura__sum'] or 0
    print("\n" + "-"*60)
    print(f"  💰 VALOR TOTAL IMPORTADO: R$ {total_valor:,.2f}")
    print("-"*60)
    
else:
    print("\n⚠️  Nenhum dado FPD foi importado ainda.")
    print("\n💡 Para importar dados FPD:")
    print("   POST /api/bonus-m10/importar-fpd/")
    print("   Arquivo: Excel ou CSV com campos NR_ORDEM, ID_CONTRATO, etc.")

print("\n" + "="*60)
print("  FORMAS DE ACESSAR OS DADOS FPD")
print("="*60 + "\n")

print("1️⃣  Admin Django:")
print("   http://localhost:8000/admin/crm_app/importacaofpd/")

print("\n2️⃣  API - Dados de uma O.S:")
print("   GET /api/bonus-m10/dados-fpd/?os=OS-00123")

print("\n3️⃣  API - Listar com filtros:")
print("   GET /api/bonus-m10/importacoes-fpd/?status=PAGO&mes=2025-01")

print("\n4️⃣  Django Shell:")
print("   python manage.py shell")
print("   >>> from crm_app.models import ImportacaoFPD")
print("   >>> ImportacaoFPD.objects.all()")

print("\n" + "="*60 + "\n")
