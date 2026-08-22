"""Detalhe vendas maio/2026 — antecipação, sábado, valores, status."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_service import (
    annotate_data_folha_comissao,
    data_instalacao_efetiva_folha,
    origem_adiantamento_comissao_venda,
)
from crm_app.services.adiantamento_sabado_service import (
    comissao_ja_adiantada_venda,
    valor_pago_adiantamento_sabado_venda,
    venda_entra_estorno_adiantamento_sabado_mes,
)

VENDEDORES = {"PAULO": None, "GEOVANNE": None, "PATRICIA": None}
ANO, MES = 2026, 5
di = datetime(ANO, MES, 1).date()
df = datetime(ANO, MES + 1, 1).date() if MES < 12 else datetime(ANO + 1, 1, 1).date()


def main() -> None:
    User = get_user_model()
    for nome in VENDEDORES:
        consultor = User.objects.filter(username__iexact=nome).first()
        if not consultor:
            print(f"\n{nome}: nao encontrado")
            continue

        qs = annotate_data_folha_comissao(
            __import__("crm_app.models", fromlist=["Venda"]).Venda.objects.filter(
                vendedor=consultor,
                ativo=True,
                status_esteira__nome__iexact="INSTALADA",
            )
        ).filter(
            data_folha_comissao__gte=di,
            data_folha_comissao__lt=df,
        ).select_related("plano", "cliente", "forma_pagamento", "status_esteira")

        print(f"\n{'=' * 90}")
        print(f"=== {nome} — {len(qs)} instaladas na folha {MES:02d}/{ANO} ===")
        total_a_pagar = 0.0
        total_antecip = 0.0
        for v in qs.order_by("data_folha_comissao", "id"):
            cliente = (v.cliente.nome_razao_social or "")[:30] if v.cliente else "-"
            plano = v.plano.nome if v.plano else "-"
            forma = (v.forma_pagamento.nome if v.forma_pagamento else "") or "-"
            antecip = comissao_ja_adiantada_venda(v)
            origem = origem_adiantamento_comissao_venda(v) or "-"
            sab_val = valor_pago_adiantamento_sabado_venda(v)
            estorno = venda_entra_estorno_adiantamento_sabado_mes(v, di, df)
            dfc = getattr(v, "data_folha_comissao", None) or data_instalacao_efetiva_folha(v)
            print(
                f"#{v.id:5} | {cliente:30} | {plano:10} | {forma:8} "
                f"| antecip={antecip} | sab={bool(v.adiantamento_sabado_marcado)} "
                f"| sab_val=R${sab_val:.0f} | origem={origem:22} "
                f"| folha={dfc} | os={v.ordem_servico or '-'}"
            )
            if antecip:
                total_antecip += sab_val if sab_val else 0
            else:
                total_a_pagar += 1

        print(f"  Qtd NAO antecipada (a pagar): {total_a_pagar}")
        print(f"  Soma sabado pago (antecipadas): R$ {total_antecip:.2f}")


if __name__ == "__main__":
    main()
