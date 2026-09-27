import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import SyncStatusEsteiraExecucao
import json

qs = SyncStatusEsteiraExecucao.objects.filter(modo='consulta_aba').order_by('-id')[:5]

for ex in qs:
    print(f"ID: {ex.id}")
    print(f"Status: {ex.status}")
    print(f"Mensagem de Erro: {ex.mensagem_erro}")
    print(f"Iniciado em: {ex.iniciado_em}")
    print(f"Finalizado em: {ex.finalizado_em}")
    print(f"Processados: {ex.processados} / {ex.total_pedidos}")
    print("-" * 40)
    if ex.relatorio_json and isinstance(ex.relatorio_json, dict):
        detalhes = ex.relatorio_json.get('detalhes', [])
        for det in detalhes[:5]:
            if det.get('erro'):
                print(f"Erro em OS {det.get('os')}: {det.get('erro')}")
    print("=" * 80)
