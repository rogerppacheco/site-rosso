"""Auditoria PAULO maio/2026 — diferença R$ 150 financeiro vs folha."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_service import (
    annotate_data_folha_comissao,
    calcular_folha_mes,
    get_valor_from_faixa,
    origem_adiantamento_comissao_venda,
    plano_tipo_to_chave,
)
from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda
from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

# Planilha financeiro PORTUGA/PAULO maio
FIN_VALORES = {
    6549: 150.0,   # ELISANGELA
    6495: 130.0,   # SAMUEL
    6453: 130.0,   # VANESSA
    6444: 150.0,   # MARISA
    6328: 170.0,   # PATRICIA 700MB
    6275: 170.0,   # MATEUS 700MB
    6232: 0.0,     # NILSON - antecipada
    6193: 0.0,     # POLLYANA - antecipada
    6177: 130.0,   # MAKENSON
    6154: 150.0,   # PALOMA
    6126: 150.0,   # DEIVID
    5973: 130.0,   # SONIA
    5933: 0.0,     # RICHARD - antecipada
    5796: 130.0,   # LUCIA
    5763: 150.0,   # FLAVIA
    5719: 130.0,   # ANA BEATRIZ MEI
    5707: 150.0,   # ERIKA
    5683: 130.0,   # FREDERICO
}
DESCONTOS_FIN = 75.0  # 25 antecip + 50 CNPJ
TOTAL_FIN_CELULA = 1925.0

ANO, MES = 2026, 5
di = datetime(ANO, MES, 1).date()
df = datetime(ANO, MES + 1, 1).date()


def main() -> None:
    u = get_user_model().objects.get(username__iexact="PAULO")
    folha = calcular_folha_mes(ANO, MES, vendedor_id=u.id)
    vd = folha["vendedores"][0]
    r = vd["resumo"]
    liquido_sis = float(r.get("liquido") or 0)

    soma_bruta = sum(FIN_VALORES.values())
    liquido_fin_soma = soma_bruta - DESCONTOS_FIN

    print("=== PAULO (username PAULO) — maio/2026 ===")
    print(f"Usuario: id={u.id} username={u.username} nome={u.get_full_name()}")
    print(f"Sistema liquido:          R$ {liquido_sis:,.2f}")
    print(f"Financeiro (soma-R$75):   R$ {liquido_fin_soma:,.2f}")
    print(f"Financeiro (celula plan): R$ {TOTAL_FIN_CELULA:,.2f}")
    print(f"Diferenca vs sistema:   R$ {liquido_sis - TOTAL_FIN_CELULA:,.2f}")
    print(f"Diferenca soma vs celula: R$ {liquido_fin_soma - TOTAL_FIN_CELULA:,.2f}")

    faixa_nome = r.get("faixa_aplicada")
    print(f"\nFaixa sistema: {faixa_nome}")
    print(f"Comissao sistema: R$ {float(r.get('comissao_total_geral') or 0):,.2f}")
    print("Descontos sistema:")
    for d in r.get("detalhes_descontos") or []:
        print(f"  - {d.get('motivo')}: R$ {float(d.get('valor') or 0):.2f} (qtd={d.get('quantidade')})")

    # Faixa valores
    from crm_app.models import RegraComissaoFaixa
    from django.db.models import Q

    q_comissao = Q(finalidade="COMISSAO") | Q(finalidade__isnull=True)
    faixa = (
        RegraComissaoFaixa.objects.filter(q_comissao, perfil="Vendedor", vendedor__isnull=True)
        .order_by("min_vendas")
        .first()
    )

    vendas = annotate_data_folha_comissao(
        Venda.objects.filter(vendedor=u, ativo=True, status_esteira__nome__iexact="INSTALADA")
    ).filter(data_folha_comissao__gte=di, data_folha_comissao__lt=df).select_related(
        "cliente", "forma_pagamento", "plano", "status_esteira"
    )

    print(f"\n--- Comparativo venda a venda ({vendas.count()} instaladas) ---")
    diff_total = 0.0
    for v in vendas.order_by("id"):
        nome = (v.cliente.nome_razao_social or "")[:32]
        forma = (v.forma_pagamento.nome if v.forma_pagamento else "-")[:12]
        chave = plano_tipo_to_chave(v.plano.nome if v.plano else "", tipo_cliente_comissao(v))
        val_sis = float(get_valor_from_faixa(faixa, chave) or 0) if faixa and chave else 0.0
        if not comissao_ja_adiantada_venda(v):
            val_sis_pagar = val_sis
        else:
            val_sis_pagar = 0.0
        val_fin = FIN_VALORES.get(v.id)
        antecip = comissao_ja_adiantada_venda(v)
        origem = origem_adiantamento_comissao_venda(v) or "-"
        delta = (val_sis_pagar - (val_fin or 0)) if val_fin is not None else None
        if delta and abs(delta) > 0.01:
            diff_total += delta
            flag = " <<<"
        else:
            flag = ""
        print(
            f"#{v.id:5} {nome:32} | {forma:12} | fin={val_fin} sis_a_pagar={val_sis_pagar:.0f} "
            f"antecip={antecip} ({origem}) delta={delta}{flag}"
        )

    print(f"\nSoma deltas (sis a pagar - fin): R$ {diff_total:.2f}")

    print("\n--- 3 zeradas (antecipada esteira) ---")
    for vid in (6232, 6193, 5933):
        v = Venda.objects.select_related("cliente").get(pk=vid)
        print(
            f"#{vid} {(v.cliente.nome_razao_social or '')[:35]} "
            f"antecipacao_comissao={v.antecipacao_comissao} "
            f"reemissao={v.reemissao} ja_adiantada={comissao_ja_adiantada_venda(v)}"
        )


if __name__ == "__main__":
    main()
