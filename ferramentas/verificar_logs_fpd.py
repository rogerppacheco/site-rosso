#!/usr/bin/env python
"""
Verificar logs de ImportacaoFPD para entender por que não foram vinculadas
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import LogImportacaoFPD

print("=" * 80)
print("LOGS DE IMPORTAÇÃO FPD")
print("=" * 80)

logs = LogImportacaoFPD.objects.all().order_by('-criado_em')

for log in logs[:5]:
    print(f"\n📋 {log.criado_em.strftime('%Y-%m-%d %H:%M:%S')} - {log.nome_arquivo}")
    print(f"   Status: {log.status}")
    print(f"   Total linhas: {log.total_linhas}")
    print(f"   Total processadas: {log.total_processadas}")
    print(f"   Total contratos não encontrados: {log.total_contratos_nao_encontrados}")
    print(f"   Total erros: {log.total_erros}")
    if log.mensagem_erro:
        print(f"   ⚠️  Erro: {log.mensagem_erro[:100]}")
    if log.exemplos_nao_encontrados:
        print(f"   Exemplos não encontrados: {log.exemplos_nao_encontrados}")

print("\n" + "=" * 80)
