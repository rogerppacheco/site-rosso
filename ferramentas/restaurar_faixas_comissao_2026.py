"""
Restaura tabelas de comissão (Regras por Faixa — finalidade COMISSÃO) em produção.

Fonte: data/comissao_export/REGRAS_FAIXAS.json + tabelas 2026 informadas pelo usuário.
Não altera ADIANTAMENTO nem ComissaoOperadora (recebimento operadora).

Uso:
  railway run python ferramentas/restaurar_faixas_comissao_2026.py          # dry-run
  railway run python ferramentas/restaurar_faixas_comissao_2026.py --apply  # aplica
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import transaction

from crm_app.models import PlanoValoresComissao, RegraComissaoFaixa

# PAP/CNPJ por perfil e faixa (ids de produção Railway, jun/2026)
FAIXAS_COMISSAO: list[dict] = [
    {
        'id': 1,
        'perfil': 'Supervisor',
        'faixa_nome': '1 a 39 Vendas',
        'min_vendas': 1,
        'max_vendas': 39,
        'valor_500mb_pap': Decimal('200'),
        'valor_700mb_pap': Decimal('220'),
        'valor_1gb_pap': Decimal('250'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
    {
        'id': 2,
        'perfil': 'Supervisor',
        'faixa_nome': '40 a 49 Vendas',
        'min_vendas': 40,
        'max_vendas': 49,
        'valor_500mb_pap': Decimal('220'),
        'valor_700mb_pap': Decimal('240'),
        'valor_1gb_pap': Decimal('270'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
    {
        'id': 3,
        'perfil': 'Supervisor',
        'faixa_nome': '50 Acima',
        'min_vendas': 50,
        'max_vendas': 9999,
        'valor_500mb_pap': Decimal('230'),
        'valor_700mb_pap': Decimal('250'),
        'valor_1gb_pap': Decimal('280'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
    {
        'id': 4,
        'perfil': 'Vendedor',
        'faixa_nome': 'Faixa 1',
        'min_vendas': 1,
        'max_vendas': 20,
        'valor_500mb_pap': Decimal('150'),
        'valor_700mb_pap': Decimal('190'),
        'valor_1gb_pap': Decimal('220'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
    {
        'id': 5,
        'perfil': 'Vendedor',
        'faixa_nome': 'Faixa 2',
        'min_vendas': 21,
        'max_vendas': 39,
        'valor_500mb_pap': Decimal('180'),
        'valor_700mb_pap': Decimal('220'),
        'valor_1gb_pap': Decimal('240'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
    {
        'id': 6,
        'perfil': 'Vendedor',
        'faixa_nome': 'Faixa 3',
        'min_vendas': 40,
        'max_vendas': 50,
        'valor_500mb_pap': Decimal('190'),
        'valor_700mb_pap': Decimal('230'),
        'valor_1gb_pap': Decimal('250'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
    {
        'id': 7,
        'perfil': 'Vendedor',
        'faixa_nome': 'Faixa 4',
        'min_vendas': 51,
        'max_vendas': 99999,
        'valor_500mb_pap': Decimal('200'),
        'valor_700mb_pap': Decimal('240'),
        'valor_1gb_pap': Decimal('260'),
        'valor_500mb_cnpj': Decimal('250'),
        'valor_700mb_cnpj': Decimal('280'),
        'valor_1gb_cnpj': Decimal('300'),
    },
]

# Referência por banda (1ª faixa vendedor) — evita override errado na folha
PLANO_VALORES_POR_BANDA = {
    '500MB': {'valor_pap': Decimal('150'), 'valor_cnpj': Decimal('250')},
    '700MB': {'valor_pap': Decimal('190'), 'valor_cnpj': Decimal('280')},
    '1GB': {'valor_pap': Decimal('220'), 'valor_cnpj': Decimal('300')},
}


def _fmt(r: RegraComissaoFaixa) -> str:
    return (
        f'id={r.id} {r.perfil} {r.faixa_nome} {r.min_vendas}-{r.max_vendas} | '
        f'PAP {r.valor_500mb_pap}/{r.valor_700mb_pap}/{r.valor_1gb_pap} | '
        f'CNPJ {r.valor_500mb_cnpj}/{r.valor_700mb_cnpj}/{r.valor_1gb_cnpj}'
    )


def restaurar(*, apply: bool) -> None:
    print('Modo:', 'APLICAR' if apply else 'DRY-RUN (sem gravar)')
    print()

    for dados in FAIXAS_COMISSAO:
        rid = dados['id']
        try:
            regra = RegraComissaoFaixa.objects.get(
                pk=rid, finalidade='COMISSAO', vendedor__isnull=True,
            )
        except RegraComissaoFaixa.DoesNotExist:
            print(f'[ERRO] Regra id={rid} não encontrada ou não é COMISSÃO geral.')
            continue

        print(f'ANTES  {_fmt(regra)}')
        campos = {
            k: v for k, v in dados.items()
            if k not in ('id', 'perfil')
        }
        depois = {**{f: getattr(regra, f) for f in campos}, **campos}
        print(
            f'DEPOIS id={rid} {dados["perfil"]} {campos["faixa_nome"]} '
            f'{campos["min_vendas"]}-{campos["max_vendas"]} | '
            f'PAP {campos["valor_500mb_pap"]}/{campos["valor_700mb_pap"]}/{campos["valor_1gb_pap"]} | '
            f'CNPJ {campos["valor_500mb_cnpj"]}/{campos["valor_700mb_cnpj"]}/{campos["valor_1gb_cnpj"]}',
        )
        if apply:
            for campo, valor in campos.items():
                setattr(regra, campo, valor)
            regra.save(update_fields=list(campos.keys()))
        print()

    print('--- PlanoValoresComissao (desativa propagação automática) ---')
    for pv in PlanoValoresComissao.objects.select_related('plano').all():
        ref = PLANO_VALORES_POR_BANDA.get(pv.banda_comissao, {})
        print(
            f'  {pv.plano.nome}: antes pap={pv.valor_pap} cnpj={pv.valor_cnpj} '
            f'prop_faixas={pv.propagar_faixas} | depois pap={ref.get("valor_pap")} '
            f'cnpj={ref.get("valor_cnpj")} propagar=False',
        )
        if apply and ref:
            pv.valor_pap = ref['valor_pap']
            pv.valor_cnpj = ref['valor_cnpj']
            pv.propagar_faixas = False
            pv.propagar_vendedores = False
            pv.save(update_fields=['valor_pap', 'valor_cnpj', 'propagar_faixas', 'propagar_vendedores'])
            plano = pv.plano
            if plano.comissao_base != ref['valor_pap']:
                plano.comissao_base = ref['valor_pap']
                plano.save(update_fields=['comissao_base'])

    if apply:
        adiant = list(
            RegraComissaoFaixa.objects.filter(finalidade='ADIANTAMENTO').values_list('id', flat=True),
        )
        print(f'\nAdiantamento preservado (ids {adiant}).')
        print('Correção aplicada com sucesso.')
    else:
        print('\nNenhuma alteração gravada. Rode com --apply para corrigir produção.')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Grava no banco')
    args = parser.parse_args()
    with transaction.atomic():
        restaurar(apply=args.apply)
        if not args.apply:
            transaction.set_rollback(True)


if __name__ == '__main__':
    main()
