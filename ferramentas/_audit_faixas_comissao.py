"""Auditoria rápida das faixas de comissão (uso: railway run python ferramentas/_audit_faixas_comissao.py)."""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ComissaoOperadora, RegraComissaoFaixa

print('=== REGRAS COMISSAO (gerais, vendedor nulo) ===')
for r in RegraComissaoFaixa.objects.filter(
    finalidade='COMISSAO', vendedor__isnull=True,
).order_by('perfil', 'min_vendas'):
    print(
        f'id={r.id} {r.perfil:10} {r.faixa_nome:20} '
        f'{r.min_vendas:3}-{r.max_vendas:5} | '
        f'PAP 500={r.valor_500mb_pap} 700={r.valor_700mb_pap} 1G={r.valor_1gb_pap} | '
        f'CNPJ 500={r.valor_500mb_cnpj} 700={r.valor_700mb_cnpj} 1G={r.valor_1gb_cnpj}',
    )

print('\n=== ADIANTAMENTO (nao alterar) ===')
for r in RegraComissaoFaixa.objects.filter(finalidade='ADIANTAMENTO').order_by('perfil', 'min_vendas'):
    print(
        f'id={r.id} {r.perfil or "-":10} {r.faixa_nome:20} '
        f'{r.min_vendas:3}-{r.max_vendas:5} | '
        f'500={r.valor_500mb_pap} 700={r.valor_700mb_pap} 1G={r.valor_1gb_pap}',
    )

print('\n=== COMISSAO OPERADORA (recebimento — nao confundir com pagamento) ===')
for co in ComissaoOperadora.objects.select_related('plano').order_by('plano__nome')[:15]:
    print(f'  {co.plano.nome}: valor_base={co.valor_base}')
