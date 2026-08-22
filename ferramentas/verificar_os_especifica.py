"""
Script para investigar uma O.S específica no banco de dados
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD, LogImportacaoFPD

def buscar_os(numero_os):
    print("=" * 80)
    print(f"🔍 INVESTIGANDO O.S: {numero_os}")
    print("=" * 80)
    print()
    
    # Variações possíveis do número
    variacoes = [
        numero_os,
        numero_os.strip(),
        numero_os.lstrip('0'),  # Sem zeros à esquerda
        f"OS-{numero_os}",
        f"OS-{numero_os.lstrip('0')}",
        numero_os.zfill(10),  # Com zeros à esquerda (10 dígitos)
        numero_os.zfill(8),   # Com zeros à esquerda (8 dígitos)
    ]
    
    print("📋 VARIAÇÕES TESTADAS:")
    for v in variacoes:
        print(f"   • '{v}'")
    print()
    
    # 1. Buscar em ContratoM10
    print("=" * 80)
    print("🏢 BUSCANDO EM CONTRATO M10")
    print("=" * 80)
    
    encontrados_contrato = []
    for variacao in variacoes:
        contratos = ContratoM10.objects.filter(ordem_servico__iexact=variacao)
        if contratos.exists():
            encontrados_contrato.extend(contratos)
            print(f"✅ Encontrado com '{variacao}':")
            for c in contratos:
                print(f"   ID: {c.id}")
                print(f"   Número Contrato: {c.numero_contrato}")
                print(f"   Cliente: {c.cliente_nome}")
                print(f"   Ordem Serviço: '{c.ordem_servico}'")
                print(f"   Status: {c.status_contrato}")
                print()
    
    if not encontrados_contrato:
        print("❌ NÃO ENCONTRADO em ContratoM10 com nenhuma variação")
        print()
        print("💡 POSSÍVEIS CAUSAS:")
        print("   1. O contrato ainda não foi importado para o sistema M10")
        print("   2. O número da O.S está em formato diferente")
        print("   3. O campo ordem_servico está vazio/nulo")
        print()
        
        # Buscar parcial
        print("🔎 Buscando parcialmente...")
        parciais = ContratoM10.objects.filter(ordem_servico__icontains=numero_os.lstrip('0')[:5])
        if parciais.exists():
            print(f"⚠️  Encontrados {parciais.count()} contratos com números similares:")
            for c in parciais[:10]:
                print(f"   • O.S: '{c.ordem_servico}' - Cliente: {c.cliente_nome}")
    
    print()
    
    # 2. Buscar em ImportacaoFPD
    print("=" * 80)
    print("📦 BUSCANDO EM IMPORTAÇÃO FPD")
    print("=" * 80)
    
    encontrados_fpd = []
    for variacao in variacoes:
        importacoes = ImportacaoFPD.objects.filter(nr_ordem__iexact=variacao)
        if importacoes.exists():
            encontrados_fpd.extend(importacoes)
            print(f"✅ Encontrado com '{variacao}':")
            for imp in importacoes:
                print(f"   ID: {imp.id}")
                print(f"   Nr Ordem: '{imp.nr_ordem}'")
                print(f"   Nr Fatura: {imp.nr_fatura}")
                print(f"   Status Fatura: {imp.ds_status_fatura}")
                print(f"   Valor: R$ {imp.vl_fatura}")
                print(f"   Vencimento: {imp.dt_venc_orig}")
                print(f"   Importada em: {imp.importada_em}")
                if imp.contrato_m10:
                    print(f"   Vinculado ao Contrato: {imp.contrato_m10.numero_contrato}")
                else:
                    print(f"   ⚠️  SEM vínculo com ContratoM10")
                print()
    
    if not encontrados_fpd:
        print("❌ NÃO ENCONTRADO em ImportacaoFPD")
        print()
        print("💡 POSSÍVEIS CAUSAS:")
        print("   1. A importação falhou (O.S não existe em ContratoM10)")
        print("   2. Nenhuma importação FPD foi realizada ainda")
        print("   3. O número da O.S no arquivo FPD está diferente")
        print()
        
        # Buscar parcial
        print("🔎 Buscando parcialmente...")
        parciais = ImportacaoFPD.objects.filter(nr_ordem__icontains=numero_os.lstrip('0')[:5])
        if parciais.exists():
            print(f"⚠️  Encontrados {parciais.count()} registros FPD com números similares:")
            for imp in parciais[:10]:
                print(f"   • Nr Ordem: '{imp.nr_ordem}' - Status: {imp.ds_status_fatura}")
    
    print()
    
    # 3. Verificar nos logs de importação
    print("=" * 80)
    print("📋 VERIFICANDO LOGS DE IMPORTAÇÃO")
    print("=" * 80)
    
    logs = LogImportacaoFPD.objects.all().order_by('-iniciado_em')
    
    if logs.exists():
        print(f"Total de logs: {logs.count()}")
        print()
        
        for log in logs[:5]:
            print(f"📄 Log: {log.nome_arquivo}")
            print(f"   Data: {log.iniciado_em}")
            print(f"   Status: {log.status}")
            print(f"   Total linhas: {log.total_linhas}")
            print(f"   Processadas: {log.total_processadas}")
            print(f"   Contratos não encontrados: {log.total_contratos_nao_encontrados}")
            
            # Verificar se a O.S está nos exemplos não encontrados
            if log.exemplos_nao_encontrados:
                for variacao in variacoes:
                    if variacao in log.exemplos_nao_encontrados:
                        print(f"   🔴 ENCONTRADO nos exemplos NÃO encontrados com '{variacao}'!")
                        print(f"   Motivo: Esta O.S não existe em ContratoM10")
                        break
            print()
    else:
        print("❌ Nenhum log de importação encontrado")
    
    print()
    print("=" * 80)
    print("📊 RESUMO")
    print("=" * 80)
    
    if encontrados_contrato and encontrados_fpd:
        print("✅ Status: TUDO OK")
        print("   A O.S existe em ContratoM10 E em ImportacaoFPD")
        print("   Deveria aparecer na validação!")
    elif encontrados_contrato and not encontrados_fpd:
        print("⚠️  Status: PARCIAL")
        print("   A O.S existe em ContratoM10 MAS NÃO foi importada no FPD")
        print("   Solução: Fazer a importação do arquivo FPD")
    elif not encontrados_contrato and encontrados_fpd:
        print("🔴 Status: INCONSISTENTE")
        print("   A O.S FOI importada no FPD mas NÃO existe em ContratoM10")
        print("   Isso NÃO deveria acontecer com a lógica atual!")
    else:
        print("🔴 Status: NÃO ENCONTRADO")
        print("   A O.S NÃO existe em nenhuma tabela")
        print()
        print("💡 PRÓXIMOS PASSOS:")
        print("   1. Verificar se o número está correto: 07309961")
        print("   2. Importar o contrato M10 desta O.S primeiro")
        print("   3. Depois importar o arquivo FPD")
    
    print()
    print("=" * 80)

if __name__ == '__main__':
    numero = input("Digite o número da O.S (ou Enter para usar 07309961): ").strip()
    if not numero:
        numero = "07309961"
    
    buscar_os(numero)
