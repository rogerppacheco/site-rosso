"""
Script para verificar se dados FPD estão sendo salvos no banco
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10, LogImportacaoFPD

print("🔍 VERIFICANDO DADOS NO BANCO")
print("=" * 80)

# Verificar ImportacaoFPD
print("\n📊 ImportacaoFPD:")
total_fpd = ImportacaoFPD.objects.count()
print(f"   Total de registros: {total_fpd}")

if total_fpd > 0:
    # Primeiros 5
    print("\n   Primeiros 5 registros:")
    for fpd in ImportacaoFPD.objects.all()[:5]:
        contrato_str = f"M10 ID: {fpd.contrato_m10.id}" if fpd.contrato_m10 else "Sem M10"
        print(f"      - O.S: {fpd.nr_ordem}, Fatura: {fpd.nr_fatura}, Valor: R$ {fpd.vl_fatura}, {contrato_str}")
    
    # Com e sem vínculo
    com_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=False).count()
    sem_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=True).count()
    
    print(f"\n   Com vínculo M10: {com_vinculo}")
    print(f"   Sem vínculo M10: {sem_vinculo}")
else:
    print("   ⚠️  Tabela VAZIA - nenhum registro!")

# Verificar ContratoM10
print("\n📊 ContratoM10:")
total_m10 = ContratoM10.objects.count()
print(f"   Total de contratos: {total_m10}")

if total_m10 > 0:
    # Ver alguns com O.S
    com_os = ContratoM10.objects.exclude(ordem_servico__isnull=True).exclude(ordem_servico='')[:5]
    print(f"\n   Primeiros 5 com O.S:")
    for contrato in com_os:
        print(f"      - O.S: {contrato.ordem_servico}, Cliente: {contrato.cliente_nome}")
else:
    print("   ⚠️  VAZIO - nenhum contrato M10 cadastrado!")

# Verificar Logs
print("\n📊 LogImportacaoFPD:")
total_logs = LogImportacaoFPD.objects.count()
print(f"   Total de logs: {total_logs}")

if total_logs > 0:
    # Último log
    ultimo_log = LogImportacaoFPD.objects.latest('iniciado_em')
    print(f"\n   Último log:")
    print(f"      Arquivo: {ultimo_log.nome_arquivo}")
    print(f"      Status: {ultimo_log.status}")
    print(f"      Total linhas: {ultimo_log.total_linhas}")
    print(f"      Processadas: {ultimo_log.total_processadas}")
    print(f"      Erros: {ultimo_log.total_erros}")
    print(f"      Sem contrato M10: {ultimo_log.total_contratos_nao_encontrados}")
    if ultimo_log.mensagem_erro:
        print(f"      Mensagem: {ultimo_log.mensagem_erro}")

print("\n" + "=" * 80)

# Diagnóstico
print("\n💡 DIAGNÓSTICO:")

if total_fpd == 0 and total_m10 == 0:
    print("   ❌ PROBLEMA: Nem ImportacaoFPD nem ContratoM10 têm dados!")
    print("   CAUSA: O código pode estar dando erro silencioso ou não salvando")
    print("   SOLUÇÃO: Verificar logs de erro do último import")
elif total_fpd == 0 and total_m10 > 0:
    print("   ⚠️  PROBLEMA: ContratoM10 tem dados mas ImportacaoFPD está vazia")
    print("   CAUSA: Importação FPD pode estar falhando")
    print("   SOLUÇÃO: Verificar erros no log de importação")
elif total_fpd > 0 and total_m10 == 0:
    print("   ✅ ImportacaoFPD tem dados (salvos sem contrato M10)")
    print("   ⚠️  ContratoM10 está vazio - nenhum vínculo possível")
    print("   PRÓXIMO PASSO: Importar base ContratoM10")
else:
    print("   ✅ Ambas as tabelas têm dados!")
    print("   Verificar se vinculação está correta")

print()
