"""Reconciliação linha a linha — CAIO maio/2026: financeiro R$ 670 vs sistema R$ 690."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from crm_app.comissao_folha_service import calcular_folha_mes
from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

FINANCEIRO: dict[str, float] = {
    "35881892000161": 0.0,
    "07820043695": 0.0,
    "06246568610": 0.0,
    "84305843668": 0.0,
    "04376100633": 0.0,
    "14128067636": 0.0,
    "12405619628": 0.0,
    "01196304602": 0.0,
    "11508287651": 0.0,
    "00875550185": 0.0,
    "05461403603": 0.0,
    "02339207657": 0.0,
    "01898369623": 160.0,
    "06531276690": 160.0,
    "86902792615": 160.0,
    "32824769000110": 160.0,
    "35405184000154": 160.0,
    "65870611687": 200.0,
    "01633367681": 200.0,
    "17251108658": 220.0,
    "58356330000102": 250.0,
}
DESCONTOS_FIN = {"adiantamentos": 850.0, "cnpj": 100.0, "antecip_inst": 50.0}

CAIO_ID = 22
ANO, MES = 2026, 5


def _norm_doc(doc: str | None) -> str:
    return "".join(c for c in str(doc or "") if c.isdigit())


def contribuicao_sistema_liquido(
    venda_id: int,
    *,
    a_pagar_ids: set[int],
    complemento_map: dict[int, float],
    boleto_ids: set[int],
    unit_boleto: float,
) -> tuple[float, str]:
    """Estima quanto a venda contribui (+) ou não para o líquido do sistema."""
    if venda_id in a_pagar_ids:
        gross = {
            5898: 180.0,
            6036: 180.0,
            6021: 220.0,
            6568: 220.0,
            6707: 220.0,
        }[venda_id]
        desc_bol = unit_boleto if venda_id in boleto_ids else 0.0
        return gross - desc_bol, f"a_pagar bruto {gross} - boleto {desc_bol}"
    if venda_id in complemento_map:
        comp = complemento_map[venda_id]
        desc_bol = unit_boleto if venda_id in boleto_ids else 0.0
        return comp - desc_bol, f"complemento sab {comp} - boleto {desc_bol}"
    if venda_id == 5864:
        return 0.0, "IDSJ sabado quitado integral (ja pago, sem complemento)"
    return 0.0, "antecipada/referencia (0 no liquido)"


def main() -> None:
    folha = calcular_folha_mes(ANO, MES, vendedor_id=CAIO_ID)
    vd = folha["vendedores"][0]
    r = vd["resumo"]

    comp_info = r["info_comissao_adiantada"]["complemento_sabado"]
    complemento_map = {
        d["venda_id"]: float(d["complemento"])
        for d in comp_info["detalhes_vendas"]
    }
    a_pagar_ids = {5898, 6036, 6021, 6568, 6707}

    from crm_app.services.cnpj_mei_service import elegivel_desconto_boleto_folha

    vendas_mes = list(
        Venda.objects.filter(vendedor_id=CAIO_ID, ativo=True).select_related(
            "cliente", "forma_pagamento", "plano"
        )
    )
    boleto_ids = {v.id for v in vendas_mes if elegivel_desconto_boleto_folha(v)}
    unit_boleto = 20.0

    por_doc: dict[str, Venda] = {}
    for v in vendas_mes:
        doc = _norm_doc(v.cliente.cpf_cnpj if v.cliente else "")
        if doc in FINANCEIRO and doc not in por_doc:
            por_doc[doc] = v

    print("=== Reconciliação CAIO maio/2026 ===\n")
    print(f"Sistema líquido:    R$ {float(r['liquido']):.2f}")
    print(f"Financeiro líquido: R$ {sum(FINANCEIRO.values()) - sum(DESCONTOS_FIN.values()):.2f}\n")

    total_fin = 0.0
    total_sis = 0.0
    print(f"{'#':>5} {'Cliente':30} {'Fin':>8} {'Sis':>8} {'Diff':>8}  Motivo")
    print("-" * 95)

    for doc, val_fin in FINANCEIRO.items():
        v = por_doc.get(doc)
        if not v:
            continue
        val_sis, motivo = contribuicao_sistema_liquido(
            v.id,
            a_pagar_ids=a_pagar_ids,
            complemento_map=complemento_map,
            boleto_ids=boleto_ids,
            unit_boleto=unit_boleto,
        )
        diff = val_sis - val_fin
        total_fin += val_fin
        total_sis += val_sis
        nome = (v.cliente.nome_razao_social or "")[:30]
        if val_fin != 0 or val_sis != 0:
            print(
                f"{v.id:5} {nome:30} {val_fin:8.2f} {val_sis:8.2f} {diff:+8.2f}  {motivo}"
            )

    # Descontos globais (não por venda)
    desc_sis_extra = 0.0
    print("\n--- Descontos globais (não nas linhas) ---")
    for d in r.get("detalhes_descontos") or []:
        tipo = d.get("tipo_exibicao", "")
        val = float(d.get("valor") or 0)
        if tipo == "folha_boleto_vendas":
            # já alocado por venda acima nas linhas a_pagar/complemento
            print(f"  Boleto total folha: R$ {val:.2f} (já rateado nas linhas)")
            continue
        print(f"  {d['motivo']}: R$ {val:.2f}")
        desc_sis_extra += val

    desc_fin_extra = DESCONTOS_FIN["cnpj"] + DESCONTOS_FIN["antecip_inst"] + DESCONTOS_FIN["adiantamentos"]
    print(f"\n  Financeiro adiantamentos (-850): embute esteira/sabado já pagos")
    print(f"  Financeiro CNPJ: R$ {DESCONTOS_FIN['cnpj']:.2f}")
    print(f"  Financeiro antecip inst: R$ {DESCONTOS_FIN['antecip_inst']:.2f}")

    # Sabado cancelado só no sistema
    sab_cancel = sum(
        float(d["valor"])
        for d in r.get("detalhes_descontos") or []
        if d.get("tipo_exibicao") == "folha_adiant_sabado_cancel"
    )
    print(f"\n  Sistema sabado cancelado: R$ {sab_cancel:.2f} (financeiro não tem linha equivalente)")

    liquido_fin_est = total_fin - desc_fin_extra + DESCONTOS_FIN["adiantamentos"]  # só linhas positivas - outros desc
    # Melhor: comparar componentes
    print("\n--- Totais parciais (só linhas com valor financeiro > 0) ---")
    print(f"  Soma contrib. sistema (9 linhas): R$ {total_sis:.2f}")
    print(f"  Soma financeiro (9 linhas):       R$ {total_fin:.2f}")
    print(f"  Diff nas 9 linhas:               R$ {total_sis - total_fin:+.2f}")

    print("\n--- Composição sistema ---")
    print(f"  comissao_total_geral:  R$ {float(r['comissao_total_geral']):.2f}")
    print(f"  complemento_sabado:    R$ {float(r['complemento_sabado_total']):.2f}")
    print(f"  descontos:             R$ {float(r['total_descontos']):.2f}")
    print(f"    = líquido            R$ {float(r['liquido']):.2f}")

    print("\n--- Onde está o R$ 20? ---")
    # LINDOIR: fin 160, sis 0 (antecipada esteira) -> fin paga a mais 160 no bruto
    # mas fin desconta 850 que inclui parte disso
    v_lind = por_doc.get("86902792615")
    if v_lind:
        print(f"  LINDOIR #{v_lind.id}: financeiro R$ 160, sistema R$ 0 (antecipada esteira R$ 130)")
        print("    → Financeiro trata como 'a pagar'; sistema já marcou antecipada.")

    print("  RAFAEL/ANGELICA: financeiro R$ 160 cada; sistema complemento R$ 30 - boleto R$ 20 = R$ 10 cada")
    print("    → Financeiro paga R$ 160; sistema líquido só R$ 10 por venda nessa etapa")
    print("    (diferença coberta pelo desconto -850 de adiantamentos no financeiro)")

    print("\n  Diff líquido final R$ 20 = sistema desconta R$ 150 a menos que financeiro")
    print("  no 'adiantamento sábado cancelado' (#venda estornada em maio).")
    if sab_cancel:
        print(f"  → Desconto sistema 'sábado cancelado': R$ {sab_cancel:.2f}")
        print("  → Financeiro não tem essa linha nos -850/-100/-50")


if __name__ == "__main__":
    main()
