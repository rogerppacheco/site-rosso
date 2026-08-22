"""Diagnóstico de folha maio/2026 para vendedores com divergência financeiro vs sistema."""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_service import calcular_folha_mes

VENDEDORES = ["PORTUGA", "PAULO", "GEOVANNE", "PATRICIA"]
ANO, MES = 2026, 5


def _fmt(val) -> str:
    return f"R$ {float(val or 0):,.2f}"


def main() -> None:
    folha = calcular_folha_mes(ANO, MES, use_effective_date_for_display=True)
    User = get_user_model()

    for nome in VENDEDORES:
        consultor = User.objects.filter(username__iexact=nome).first()
        if not consultor:
            print(f"\n=== {nome}: NAO ENCONTRADO ===")
            continue

        vd = next(
            (v for v in folha.get("vendedores", []) if v.get("vendedor_id") == consultor.id),
            None,
        )
        if not vd:
            print(f"\n=== {nome} (id={consultor.id}): SEM DADOS NA FOLHA ===")
            continue

        r = vd.get("resumo") or {}
        print(f"\n{'=' * 70}")
        print(f"=== {nome} (id={consultor.id}) — {MES:02d}/{ANO} ===")
        print(f"Faixa: {r.get('faixa_aplicada')} | Instalados: {r.get('total_instalados_faixa')}")
        print(f"Comissao (a pagar): {_fmt(r.get('comissao_total_geral'))}")
        print(f"Complemento sabado: {_fmt(r.get('complemento_sabado_total'))}")
        print(f"Descontos:          {_fmt(r.get('total_descontos'))}")
        print(f"Bonus:              {_fmt(r.get('total_bonus'))}")
        print(f"LIQUIDO:            {_fmt(r.get('liquido'))}")

        print("\n--- Por plano ---")
        for p in r.get("por_plano") or []:
            print(
                f"  {p.get('plano', '-'):20} | a_pagar={p.get('qtd_a_pagar', 0):2} "
                f"| antecip={p.get('qtd_antecipada', 0):2} "
                f"| val_adiant={_fmt(p.get('valor_total_antecipado'))} "
                f"| unit={_fmt(p.get('valor_unitario'))} "
                f"| total={_fmt(p.get('valor_total'))} "
                f"| comissao={_fmt(p.get('comissao'))}"
            )

        print("\n--- Descontos ---")
        for d in r.get("detalhes_descontos") or []:
            print(
                f"  [{d.get('tipo_exibicao', '-')}] {d.get('motivo', '-')} "
                f"qtd={d.get('quantidade', '-')} val={_fmt(d.get('valor'))}"
            )

        print("\n--- Bonus ---")
        for b in r.get("detalhes_bonus") or []:
            print(f"  {b.get('motivo', '-')} val={_fmt(b.get('valor'))}")

        print("\n--- Referencia (nao desconta) ---")
        ref = r.get("referencia_adiantamentos") or {}
        for k, v in ref.items():
            if v:
                print(f"  {k}: {json.dumps(v, ensure_ascii=False, default=str)}")

        print("\n--- Extrato (instaladas + referencia) ---")
        for linha in vd.get("extrato") or []:
            vid = linha.get("venda_id")
            val = linha.get("valor_comissao")
            tipo = linha.get("tipo_comissao") or linha.get("tipo_comissao_label") or "-"
            nome_cli = (linha.get("nome_cliente") or "")[:35]
            plano = linha.get("plano") or "-"
            origem = linha.get("origem_adiantamento") or "-"
            base = linha.get("base_comissao") or "-"
            print(
                f"  #{vid:5} | {nome_cli:35} | {plano:12} | {tipo:30} "
                f"| base={base:12} | origem={origem:20} | val={_fmt(val)}"
            )

        print("\n--- Alertas ---")
        for a in r.get("alertas_folha") or []:
            print(f"  {a}")


if __name__ == "__main__":
    main()
