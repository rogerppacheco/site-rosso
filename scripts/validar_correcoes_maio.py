"""Valida folha maio/2026 após correções Geovanne e Patricia."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from django.contrib.auth import get_user_model

from crm_app.comissao_folha_service import calcular_folha_mes
from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

ANO, MES = 2026, 5


def _resumo(username: str) -> None:
    u = get_user_model().objects.get(username__iexact=username)
    folha = calcular_folha_mes(ANO, MES, vendedor_id=u.id)
    vd = folha["vendedores"][0]
    r = vd["resumo"]
    print(f"\n=== {username} ===")
    print(f"  Liquido: R$ {float(r.get('liquido') or 0):.2f}")
    print(f"  Comissao: R$ {float(r.get('comissao_total_geral') or 0):.2f}")
    print(f"  Compl. sabado: R$ {float(r.get('complemento_sabado_total') or 0):.2f}")
    print(f"  Descontos: R$ {float(r.get('total_descontos') or 0):.2f}")
    ref = r.get("referencia_adiantamentos") or r.get("info_adiantamento_origem") or {}
    if ref:
        print(f"  Ref. adiant.: {ref}")
    for p in r.get("por_plano") or []:
        if p.get("qtd_antecipada") or p.get("valor_total_antecipado"):
            print(
                f"  {p.get('plano')}: antecip={p.get('qtd_antecipada')} "
                f"val_adiant=R${float(p.get('valor_total_antecipado') or 0):.2f}"
            )


def _checar_vendas() -> None:
    print("\n=== Checagens pontuais ===")
    for vid in [6102, 6503, 6532, 6506]:
        v = Venda.objects.select_related("vendedor").get(pk=vid)
        print(
            f"  #{vid} {v.vendedor.username if v.vendedor else '-'} "
            f"reemissao={v.reemissao} antecip={v.antecipacao_comissao} "
            f"sab_quitado={bool(v.adiantamento_sabado_quitado_em)} "
            f"ja_adiantada={comissao_ja_adiantada_venda(v)}"
        )


if __name__ == "__main__":
    _checar_vendas()
    _resumo("GEOVANNE")
    _resumo("PATRICIA")
