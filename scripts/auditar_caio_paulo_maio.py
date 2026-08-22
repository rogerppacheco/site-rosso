"""Auditoria Caio/PAULO maio/2026 — diferença financeiro vs folha."""
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
    origem_adiantamento_comissao_venda,
)
from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

# Planilha financeiro (PORTUGA MAIO) — valores informados
FINANCEIRO = {
    "ELISANGELA DA SILVA": 150.0,
    "SAMUEL ARAUJO DA SILVA": 130.0,
    "VANESSA APARECIDA RODRIGUES": 130.0,
    "MARISA RODRIGUES GUIMARAES": 150.0,
    "PATRICIA GOMES DOS SANTOS": 170.0,
    "MATEUS SANTOS OLIVEIRA": 170.0,
    "NILSON VICTOR DA SILVA ARAUJO": 0.0,
    "POLLYANA GABRIELLE BARBOSA SANTOS": 0.0,
    "MAKENSON AUGUSTIN": 130.0,
    "PALOMA RIBEIRO FAGUNDES": 150.0,
    "DEIVID DE JESUS CARVALHO": 150.0,
    "SONIA BARROSO DA SILVA": 130.0,
    "RICHARD KELVIN CRUZ": 0.0,
    "LUCIA MARIA VIEIRA": 130.0,
    "FLAVIA HERNANI": 150.0,
    "ANA BEATRIZ DE VASCONCELOS": 130.0,
    "ERIKA XAVIER": 150.0,
    "FREDERICO DOS SANTOS CASTRO": 130.0,
}
DESCONTOS_FIN = 25.0 + 50.0  # antecip instalação + adiant CNPJ

ANO, MES = 2026, 5
di = datetime(ANO, MES, 1).date()
df = datetime(ANO, MES + 1, 1).date()


def _match_fin(nome: str) -> float | None:
    n = nome.upper()
    for k, v in FINANCEIRO.items():
        if k.split()[0] in n or n[:20] in k:
            return v
    return None


def main() -> None:
    u = get_user_model().objects.get(username__iexact="PAULO")
    folha = calcular_folha_mes(ANO, MES, vendedor_id=u.id)
    vd = folha["vendedores"][0]
    r = vd["resumo"]
    liquido_sis = float(r.get("liquido") or 0)
    comissao_sis = float(r.get("comissao_total_geral") or 0)
    desc_sis = float(r.get("total_descontos") or 0)

    soma_fin = sum(FINANCEIRO.values()) - DESCONTOS_FIN
    print(f"=== PAULO (Caio/PORTUGA) maio/2026 ===")
    print(f"Sistema liquido:     R$ {liquido_sis:,.2f}")
    print(f"Sistema comissao:    R$ {comissao_sis:,.2f}")
    print(f"Sistema descontos:   R$ {desc_sis:,.2f}")
    print(f"Financeiro liquido:  R$ {soma_fin:,.2f}  (soma valores - R$75)")
    print(f"Diferenca:           R$ {liquido_sis - soma_fin:,.2f}")

    print("\n--- Descontos sistema ---")
    for d in r.get("detalhes_descontos") or []:
        print(f"  {d.get('motivo')}: R$ {float(d.get('valor') or 0):.2f} qtd={d.get('quantidade')}")

    vendas = annotate_data_folha_comissao(
        Venda.objects.filter(
            vendedor=u, ativo=True, status_esteira__nome__iexact="INSTALADA"
        )
    ).filter(data_folha_comissao__gte=di, data_folha_comissao__lt=df).select_related(
        "cliente", "forma_pagamento", "plano", "status_esteira"
    )

    print(f"\n--- {vendas.count()} instaladas na folha maio ---")
    total_a_pagar = 0.0
    zeradas_fin = []
    for v in vendas.order_by("data_folha_comissao", "id"):
        nome = (v.cliente.nome_razao_social or "")[:40]
        forma = (v.forma_pagamento.nome if v.forma_pagamento else "-")[:15]
        antecip = comissao_ja_adiantada_venda(v)
        origem = origem_adiantamento_comissao_venda(v) or "-"
        val_fin = _match_fin(nome)
        # valor sistema na faixa
        from crm_app.comissao_folha_service import encontrar_faixa  # type: ignore
        chave_plano = v.plano.nome if v.plano else ""
        print(
            f"#{v.id:5} | {nome:40} | {forma:15} | antecip={antecip} origem={origem:20} "
            f"| fin={val_fin} | antecipacao_comissao={v.antecipacao_comissao}"
        )
        if val_fin == 0.0:
            zeradas_fin.append((v.id, nome, antecip, origem))
        if not antecip:
            # rough: count a pagar
            total_a_pagar += 1

    print("\n--- 3 zeradas no financeiro ---")
    for item in zeradas_fin:
        print(f"  #{item[0]} {item[1]} | sistema antecip={item[2]} origem={item[3]}")

    # Extrato valores
    print("\n--- Extrato (comparacao) ---")
    for linha in vd.get("extrato") or []:
        vid = linha.get("venda_id")
        if vid in (5933, 6193, 6232):
            print(f"  #{vid} val={linha.get('valor_comissao')} tipo={linha.get('comissao_tipo')} adiantada={linha.get('adiantada')}")


if __name__ == "__main__":
    main()
