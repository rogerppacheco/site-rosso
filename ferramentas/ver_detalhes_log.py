"""
Ver detalhes do log de importação específico
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import LogImportacaoFPD

log = LogImportacaoFPD.objects.first()

if log:
    print("=" * 80)
    print(f"DETALHES DO LOG: {log.nome_arquivo}")
    print("=" * 80)
    print()
    print(f"📅 Data: {log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"👤 Usuário: {log.usuario.username}")
    print(f"🎯 Status: {log.status}")
    print(f"⏱️  Duração: {log.duracao_segundos}s")
    print()
    print(f"📊 ESTATÍSTICAS:")
    print(f"   Total de linhas: {log.total_linhas}")
    print(f"   Processadas: {log.total_processadas}")
    print(f"   Erros: {log.total_erros}")
    print(f"   Contratos não encontrados: {log.total_contratos_nao_encontrados}")
    print(f"   Valor importado: R$ {log.total_valor_importado or 0:,.2f}")
    print()
    
    if log.mensagem_erro:
        print(f"❌ ERRO: {log.mensagem_erro}")
        print()
    
    if log.exemplos_nao_encontrados:
        print(f"🔍 EXEMPLOS DE O.S NÃO ENCONTRADAS ({len(log.exemplos_nao_encontrados)} exemplos):")
        print()
        for i, os in enumerate(log.exemplos_nao_encontrados, 1):
            print(f"   {i:2d}. {os}")
        
        if log.total_contratos_nao_encontrados > len(log.exemplos_nao_encontrados):
            faltam = log.total_contratos_nao_encontrados - len(log.exemplos_nao_encontrados)
            print(f"   ... e mais {faltam} não exibidos")
        
        print()
        print("💡 DICA:")
        print("   Estas ordens de serviço não existem na tabela ContratoM10.")
        print("   Verifique se:")
        print("   1. Os números estão corretos no arquivo FPD")
        print("   2. Os contratos M10 correspondentes já foram importados")
        print("   3. O campo 'ordem_servico' no ContratoM10 está preenchido")
    
    if log.detalhes_json:
        print()
        print(f"📋 DETALHES JSON:")
        print(json.dumps(log.detalhes_json, indent=2, ensure_ascii=False))
    
    print()
    print("=" * 80)
else:
    print("Nenhum log encontrado")
