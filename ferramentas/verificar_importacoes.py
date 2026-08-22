"""
Verificação rápida de importações FPD
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, LogImportacaoFPD, ContratoM10

print("\n" + "=" * 100)
print("📊 VERIFICAÇÃO DE IMPORTAÇÕES FPD")
print("=" * 100)

# 1. Verificar ImportacaoFPD
print("\n1️⃣ Tabela ImportacaoFPD:")
total_fpd = ImportacaoFPD.objects.count()
print(f"   Total de registros: {total_fpd}")

if total_fpd > 0:
    print(f"\n   Primeiros 5 registros:")
    for imp in ImportacaoFPD.objects.all()[:5]:
        print(f"   - ID: {imp.id}, O.S: {imp.nr_ordem}, Fatura: {imp.nr_fatura}, Valor: R$ {imp.vl_fatura}")

# 2. Verificar LogImportacaoFPD
print("\n2️⃣ Tabela LogImportacaoFPD:")
total_logs = LogImportacaoFPD.objects.count()
print(f"   Total de logs: {total_logs}")

if total_logs > 0:
    print(f"\n   Últimos 5 logs:")
    for log in LogImportacaoFPD.objects.order_by('-iniciado_em')[:5]:
        print(f"   - ID: {log.id}, Arquivo: {log.nome_arquivo}")
        print(f"     Status: {log.status}")
        print(f"     Linhas: {log.total_linhas}, Processadas: {log.total_processadas}")
        print(f"     Erros: {log.total_erros}")
        if log.mensagem_erro:
            print(f"     Mensagem: {log.mensagem_erro[:100]}")
        print()

# 3. Verificar ContratoM10
print("\n3️⃣ Tabela ContratoM10:")
total_m10 = ContratoM10.objects.count()
print(f"   Total de contratos: {total_m10}")

# 4. Diagnóstico
print("\n" + "=" * 100)
print("🔍 DIAGNÓSTICO:")
print("=" * 100)

if total_fpd == 0:
    print("\n❌ PROBLEMA: Nenhum registro em ImportacaoFPD!")
    print("   Possíveis causas:")
    print("   1. As importações falharam silenciosamente")
    print("   2. Os registros foram salvos em outra tabela")
    print("   3. Houve rollback nas transações")
else:
    print(f"\n✅ {total_fpd} registros encontrados em ImportacaoFPD")

if total_logs == 0:
    print("\n❌ PROBLEMA: Nenhum log de importação encontrado!")
    print("   Você está usando a interface web ou o script terminal?")
else:
    print(f"\n✅ {total_logs} logs de importação encontrados")

print("\n" + "=" * 100)
