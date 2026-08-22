"""Corrige forma_pagamento das vendas 3288, 6497, 6506 conforme OSAB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db import transaction

from crm_app.churn_os_utils import os_variantes
from crm_app.models import FormaPagamento, HistoricoAlteracaoVenda, ImportacaoOsab, Venda

IDS = [3288, 6497, 6506]


def main():
    fp_cartao = None
    for fp in FormaPagamento.objects.filter(ativo=True):
        n = (fp.nome or "").upper()
        if "CART" in n or ("CREDIT" in n or "CRÉDIT" in n) and "DEBIT" not in n and "DÉBIT" not in n:
            fp_cartao = fp
            break
    if not fp_cartao:
        print("Forma CARTÃO DE CRÉDITO não encontrada.")
        return 1

    vendas_atualizar = []
    historicos = []
    for v in Venda.objects.filter(id__in=IDS).select_related("forma_pagamento"):
        o = None
        for k in os_variantes(v.ordem_servico):
            o = ImportacaoOsab.objects.filter(documento=k).first()
            if o:
                break
        antes = v.forma_pagamento.nome if v.forma_pagamento else "-"
        osab_mp = o.meio_pagamento if o else "?"
        print(f"id={v.id} os={v.ordem_servico} {antes} -> {fp_cartao.nome} (OSAB: {osab_mp})")
        if v.forma_pagamento_id == fp_cartao.id:
            print("  já correto")
            continue
        v.forma_pagamento = fp_cartao
        vendas_atualizar.append(v)
        historicos.append(
            HistoricoAlteracaoVenda(
                venda=v,
                usuario=None,
                alteracoes={
                    "forma_pagamento": (
                        f"De '{antes}' para '{fp_cartao.nome}' "
                        "(correção manual: OSAB Cartão de Crédito x CRM Boleto)"
                    ),
                },
            )
        )

    if not vendas_atualizar:
        print("Nenhuma venda precisava de alteração.")
        return 0

    with transaction.atomic():
        Venda.objects.bulk_update(vendas_atualizar, ["forma_pagamento"])
        HistoricoAlteracaoVenda.objects.bulk_create(historicos)

    print(f"Atualizadas {len(vendas_atualizar)} vendas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
