"""Auditoria CAIO maio/2026 — diferença R$ 20 (financeiro R$ 670 vs sistema R$ 690)."""
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

from crm_app.comissao_folha_service import calcular_folha_mes

# Planilha financeiro CAIO maio/2026 (imagem)
FINANCEIRO_POR_DOC: dict[str, float] = {
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
DESCONTOS_FIN = 850.0 + 100.0 + 50.0  # R$ 1.000

ANO, MES = 2026, 5


def _norm_doc(doc: str | None) -> str:
    if not doc:
        return ""
    return "".join(c for c in str(doc) if c.isdigit())


def main() -> None:
    User = get_user_model()
    u = User.objects.filter(username__iexact="CAIO").first()
    if not u:
        for cand in User.objects.filter(first_name__icontains="caio") | User.objects.filter(
            last_name__icontains="caio"
        ):
            print(f"Candidato: id={cand.id} username={cand.username} nome={cand.get_full_name()}")
        raise SystemExit("Usuario CAIO nao encontrado")

    folha = calcular_folha_mes(ANO, MES, vendedor_id=u.id)
    vd = folha["vendedores"][0]
    r = vd["resumo"]

    liquido_sis = float(r.get("liquido") or 0)
    comissao_sis = float(r.get("comissao_total_geral") or 0)
    desc_sis = float(r.get("total_descontos") or 0)
    bonus_sis = float(r.get("total_bonus") or 0)
    comp_sab = float(r.get("complemento_sabado_total") or 0)

    soma_vendas_fin = sum(FINANCEIRO_POR_DOC.values())
    liquido_fin = soma_vendas_fin - DESCONTOS_FIN

    print(f"=== CAIO (id={u.id}) maio/2026 ===")
    print(f"Nome: {u.get_full_name() or u.username}")
    print(f"Sistema liquido:     R$ {liquido_sis:,.2f}")
    print(f"  comissao:          R$ {comissao_sis:,.2f}")
    print(f"  complemento sab:   R$ {comp_sab:,.2f}")
    print(f"  bonus:             R$ {bonus_sis:,.2f}")
    print(f"  descontos:         R$ {desc_sis:,.2f}")
    print(f"Financeiro liquido:  R$ {liquido_fin:,.2f}")
    print(f"Diferenca (sis-fin): R$ {liquido_sis - liquido_fin:,.2f}")

    print("\n--- Descontos sistema ---")
    for d in r.get("detalhes_descontos") or []:
        print(
            f"  [{d.get('tipo_exibicao')}] {d.get('motivo')}: "
            f"R$ {float(d.get('valor') or 0):.2f} qtd={d.get('quantidade')}"
        )

    print("\n--- Bonus sistema ---")
    for b in r.get("detalhes_bonus") or []:
        print(f"  {b.get('motivo')}: R$ {float(b.get('valor') or 0):.2f}")

    print("\n--- Por plano (resumo) ---")
    for p in r.get("por_plano") or []:
        print(
            f"  {p.get('plano', '-'):15} a_pagar={p.get('qtd_a_pagar', 0)} "
            f"antecip={p.get('qtd_antecipada', 0)} unit={p.get('valor_unitario')} "
            f"comissao=R$ {float(p.get('comissao') or 0):.2f}"
        )

    print("\n--- Extrato linha a linha (sistema vs financeiro) ---")
    diffs: list[tuple] = []
    soma_sis_extrato = 0.0
    for linha in vd.get("extrato") or []:
        val_sis = float(linha.get("valor_comissao") or 0)
        soma_sis_extrato += val_sis
        doc = _norm_doc(linha.get("cnpj") or linha.get("cpf") or "")
        nome = (linha.get("nome_cliente") or linha.get("nome") or "")[:40]
        val_fin = FINANCEIRO_POR_DOC.get(doc)
        diff = None if val_fin is None else round(val_sis - val_fin, 2)
        if diff and diff != 0:
            diffs.append((linha.get("venda_id"), nome, doc, val_fin, val_sis, diff))
        tipo = linha.get("comissao_tipo") or linha.get("tipo_comissao") or "-"
        base = linha.get("base_comissao") or "-"
        origem = linha.get("origem_adiantamento") or "-"
        fin_str = f"R$ {val_fin:.2f}" if val_fin is not None else "?"
        print(
            f"  #{linha.get('venda_id'):5} | {nome:38} | doc={doc[-11:]:11} "
            f"| sis={val_sis:7.2f} fin={fin_str:10} | {tipo:25} base={base:12} orig={origem}"
        )

    print(f"\nSoma extrato sistema (comissao linhas): R$ {soma_sis_extrato:,.2f}")
    print(f"Soma vendas financeiro:                  R$ {soma_vendas_fin:,.2f}")

    if diffs:
        print("\n--- DIVERGENCIAS por venda ---")
        for item in diffs:
            print(
                f"  #{item[0]} {item[1]} | fin=R$ {item[3]:.2f} sis=R$ {item[4]:.2f} "
                f"diff=R$ {item[5]:.2f}"
            )
    else:
        print("\nNenhuma divergencia por venda no extrato (valores batem ou doc nao casou).")

    # Conferir descontos
    print(f"\nDescontos financeiro: R$ {DESCONTOS_FIN:,.2f}")
    print(f"Descontos sistema:    R$ {desc_sis:,.2f}")
    print(f"Diff descontos:       R$ {desc_sis - DESCONTOS_FIN:,.2f}")

    ref = r.get("referencia_adiantamentos") or {}
    if ref:
        print("\n--- Referencia adiantamentos (nao entra no liquido) ---")
        for k, v in ref.items():
            if v:
                print(f"  {k}: {v}")

    # Linhas com valor > 0 na planilha financeiro
    print("\n--- 9 linhas pagas no financeiro (valor > 0) ---")
    positivos = {k: v for k, v in FINANCEIRO_POR_DOC.items() if v > 0}
    total_diff_pos = 0.0
    for linha in vd.get("extrato") or []:
        doc = _norm_doc(linha.get("cnpj") or linha.get("cpf") or "")
        if doc not in positivos:
            continue
        val_fin = positivos[doc]
        val_sis = float(linha.get("valor_comissao") or 0)
        diff = round(val_sis - val_fin, 2)
        total_diff_pos += diff
        tipo = linha.get("comissao_tipo") or "-"
        print(
            f"  #{linha.get('venda_id')} doc={doc} fin=R$ {val_fin:.2f} "
            f"sis=R$ {val_sis:.2f} diff=R$ {diff:+.2f} | {tipo}"
        )
    print(f"Soma diff nas 9 linhas: R$ {total_diff_pos:+.2f}")

    # Reconciliacao liquido
    print("\n--- Reconciliacao liquido ---")
    print(f"  comissao_total_geral + complemento_sabado - descontos")
    print(
        f"  {comissao_sis:.2f} + {comp_sab:.2f} - {desc_sis:.2f} "
        f"= {comissao_sis + comp_sab - desc_sis:.2f}"
    )
    print(f"  Financeiro: vendas {soma_vendas_fin:.2f} - descontos {DESCONTOS_FIN:.2f} = {liquido_fin:.2f}")


if __name__ == "__main__":
    main()
