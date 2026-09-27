import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crm_project.settings')
django.setup()
from crm_app.models import Venda

# Vendas criadas em setembro e que estão cadastradas (Esteira)
qs_cad = Venda.objects.filter(data_criacao__year=2026, data_criacao__month=9, status_tratamento__nome__iexact='CADASTRADA')
print("Cadastradas (criadas em set):", qs_cad.count())

# Vendas sem status_tratamento
qs_null = Venda.objects.filter(data_criacao__year=2026, data_criacao__month=9, status_tratamento__isnull=True)
print("Sem status tratamento (criadas em set):", qs_null.count())

# Vendas criadas em setembro COM ordem_servico
qs_os = Venda.objects.filter(data_criacao__year=2026, data_criacao__month=9, ordem_servico__isnull=False).exclude(ordem_servico='')
print("Com OS (criadas em set):", qs_os.count())

# Vendas criadas em setembro COM data_abertura
qs_abertura = Venda.objects.filter(data_criacao__year=2026, data_criacao__month=9, data_abertura__isnull=False)
print("Com data_abertura (criadas em set):", qs_abertura.count())

# Total em setembro (criadas)
print("Total criadas em set:", Venda.objects.filter(data_criacao__year=2026, data_criacao__month=9).count())

# Quantas têm 'Novo pedido', 'Aguardando tratamento', 'ANALISE_BO'
qs_analise = Venda.objects.filter(
    data_criacao__year=2026, data_criacao__month=9,
    status_tratamento__nome__in=['Aguardando tratamento', 'ANALISE_BO', 'Novo pedido', 'Não Venda', 'Pedido duplicado']
)
print("Em analise / indevidas:", qs_analise.count())
