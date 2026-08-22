"""Ajusta plano SEM MESH para comissão personalizada (produção)."""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import Plano, PlanoValoresComissao

plano = Plano.objects.filter(nome__icontains='SEM MESH', ativo=True).first()
if not plano:
    print('Plano SEM MESH não encontrado.')
    raise SystemExit(1)

vc, _ = PlanoValoresComissao.objects.update_or_create(
    plano=plano,
    defaults={
        'banda_comissao': 'PERSONALIZADO',
        'propagar_faixas': False,
        'propagar_vendedores': False,
    },
)
print(f'OK: {plano.nome} → banda={vc.banda_comissao} pap={vc.valor_pap} cnpj={vc.valor_cnpj}')
