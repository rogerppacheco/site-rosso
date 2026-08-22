"""Auditoria valores propagados por plano/config vendedor."""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ConfigComissaoVendedor, PlanoValoresComissao, PlanoValoresComissaoVendedor

print('=== PlanoValoresComissao ===')
for pv in PlanoValoresComissao.objects.select_related('plano').all():
    print(f'  {pv.plano.nome}: pap={pv.valor_pap} cnpj={pv.valor_cnpj} banda={pv.banda_comissao}')

print('\n=== PlanoValoresComissaoVendedor (amostra) ===')
for pv in PlanoValoresComissaoVendedor.objects.select_related('plano', 'config__usuario')[:20]:
    print(f'  {pv.config.usuario.username}: {pv.plano.nome} pap={pv.valor_pap} cnpj={pv.valor_cnpj}')

print('\n=== ConfigComissaoVendedor manual (templates) ===')
for c in ConfigComissaoVendedor.objects.filter(ano__isnull=True, mes__isnull=True, usar_valor_manual=True)[:10]:
    print(
        f'  {c.usuario.username}: manual 500pap={c.valor_500mb_pap_manual} '
        f'700pap={c.valor_700mb_pap_manual} 1gpap={c.valor_1gb_pap_manual}',
    )
