"""Detalhe da diferença R$ 20 — CAIO maio/2026 (produção)."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_service import (
    calcular_folha_mes,
    get_valor_from_faixa,
    plano_tipo_to_chave,
    valor_comissao_linha_extrato,
)
from crm_app.models import Venda
from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

FINANCEIRO: dict[str, tuple[str, float]] = {
    "35881892000161": ("CLEBERSON", 0.0),
    "07820043695": ("ARIANA", 0.0),
    "06246568610": ("FABIANA", 0.0),
    "84305843668": ("MARCIA", 0.0),
    "04376100633": ("ANDREIA", 0.0),
    "14128067636": ("JHENIFFER", 0.0),
    "12405619628": ("BRENO", 0.0),
    "01196304602": ("MARLUCIO", 0.0),
    "11508287651": ("JESSICA", 0.0),
    "00875550185": ("UBIRATAN", 0.0),
    "05461403603": ("WANDERSON", 0.0),
    "02339207657": ("BRYAN", 0.0),
    "01898369623": ("RAFAEL", 160.0),
    "06531276690": ("ANGELICA", 160.0),
    "86902792615": ("LINDOIR", 160.0),
    "32824769000110": ("JUSCELINO", 160.0),
    "35405184000154": ("VERA LUCIA", 160.0),
    "65870611687": ("MARIA APARECIDA", 200.0),
    "01633367681": ("ALEX", 200.0),
    "17251108658": ("BRENDO", 220.0),
    "58356330000102": ("IDSJ", 250.0),
}

VENDA_IDS_POSITIVOS = {
    6412, 6407, 6039, 6036, 5898, 6707, 6568, 6021, 5864,
}

ANO, MES = 2026, 5
CAIO_ID = 22


def _norm_doc(doc: str | None) -> str:
    if not doc:
        return ""
    return "".join(c for c in str(doc) if c.isdigit())


def main() -> None:
    folha = calcular_folha_mes(ANO, MES, vendedor_id=CAIO_ID)
    vd = folha["vendedores"][0]
    r = vd["resumo"]
    extrato_map = {e["venda_id"]: e for e in vd.get("extrato") or []}

    vendas = (
        Venda.objects.filter(id__in=FINANCEIRO.keys())
        .select_related("cliente", "plano", "forma_pagamento", "status_esteira")
    )
    # buscar por doc
    todas = Venda.objects.filter(vendedor_id=CAIO_ID, ativo=True).select_related(
        "cliente", "plano", "forma_pagamento", "status_esteira"
    )
    por_doc: dict[str, list] = {}
    for v in todas:
        doc = _norm_doc(v.cliente.cpf_cnpj if v.cliente else "")
        if doc in FINANCEIRO:
            por_doc.setdefault(doc, []).append(v)

    print("=== CAIO maio/2026 — diff R$ 20 ===\n")
    print(f"Sistema liquido: R$ {float(r['liquido']):.2f}")
    print(f"  comissao_total_geral: R$ {float(r['comissao_total_geral']):.2f}")
    print(f"  complemento_sabado:   R$ {float(r['complemento_sabado_total']):.2f}")
    print(f"  descontos:            R$ {float(r['total_descontos']):.2f}")
    fin_liq = sum(v for _, v in FINANCEIRO.values()) - 1000
    print(f"Financeiro liquido: R$ {fin_liq:.2f} (1670 - 1000)")
    print(f"Diferenca: R$ {float(r['liquido']) - fin_liq:.2f}\n")

    print("--- 9 vendas pagas no financeiro ---")
    diff_liquido = 0.0
    for doc, (apelido, val_fin) in FINANCEIRO.items():
        if val_fin <= 0:
            continue
        vs = por_doc.get(doc, [])
        if not vs:
            print(f"  {apelido:15} doc={doc} — VENDA NAO ENCONTRADA")
            continue
        v = vs[0]
        ext = extrato_map.get(v.id, {})
        val_ext = float(ext.get("valor_comissao") or 0)
        tipo = ext.get("comissao_tipo") or "-"
        plano = v.plano.nome if v.plano else "-"
        forma = v.forma_pagamento.nome if v.forma_pagamento else "-"
        diff = val_fin - val_ext  # positivo = financeiro paga MAIS que sistema mostra no extrato
        diff_liquido += -diff  # sistema - financeiro na linha
        print(
            f"  #{v.id:4} {apelido:15} | plano={plano:12} forma={forma:12} "
            f"| fin=R$ {val_fin:6.2f} extrato=R$ {val_ext:6.2f} "
            f"| sis-fin=R$ {-diff:+.2f} | {tipo[:45]}"
        )

    print(f"\nSoma (sis - fin) nas 9 linhas extrato: R$ {diff_liquido:+.2f}")

    print("\n--- Descontos sistema vs financeiro ---")
    for d in r.get("detalhes_descontos") or []:
        print(f"  {d['motivo']}: R$ {d['valor']:.2f} (qtd={d.get('quantidade')})")
    print("  Financeiro: R$ 850 (adiantamentos?) + R$ 100 (CNPJ) + R$ 50 (antecip inst)")

    print("\n--- Hipótese: complemento sábado R$ 90 ---")
    for vid in (6412, 6407, 6095, 5864):
        ext = extrato_map.get(vid, {})
        if ext:
            print(
                f"  #{vid} {ext.get('nome_cliente','')[:30]:30} "
                f"val={ext.get('valor_comissao')} tipo={ext.get('comissao_tipo')}"
            )

    # Quais entram em comissao_total_geral (a pagar, não antecipada)
    print("\n--- Vendas 'A pagar' na folha (entram em comissao_total_geral) ---")
    for linha in vd.get("extrato") or []:
        tipo = (linha.get("comissao_tipo") or "").lower()
        if "a pagar" not in tipo:
            continue
        vid = linha["venda_id"]
        val = float(linha.get("valor_comissao") or 0)
        nome = (linha.get("nome_cliente") or "")[:35]
        print(f"  #{vid} {nome:35} R$ {val:.2f}")

    print("\n--- Vendas sábado quitado (+ complemento) ---")
    for linha in vd.get("extrato") or []:
        tipo = linha.get("comissao_tipo") or ""
        if "sábado" not in tipo.lower() and "sabado" not in tipo.lower():
            continue
        if "referência" in tipo.lower() or "referencia" in tipo.lower():
            continue
        vid = linha["venda_id"]
        val = float(linha.get("valor_comissao") or 0)
        nome = (linha.get("nome_cliente") or "")[:35]
        print(f"  #{vid} {nome:35} R$ {val:.2f} | {tipo}")


if __name__ == "__main__":
    main()
