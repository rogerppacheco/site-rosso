"""Auditoria dos 8 adiantamentos sábado da Viviane — maio/2026."""
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

from crm_app.comissao_folha_service import calcular_folha_mes, origem_adiantamento_comissao_venda
from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import (
    comissao_ja_adiantada_venda,
    motivo_estorno_adiantamento_sabado,
    venda_elegivel_estorno_adiantamento_sabado,
    venda_entra_estorno_adiantamento_sabado_mes,
)

IDS = [6750, 6110, 6107, 6106, 6103, 6084, 5874, 5870]
ANO, MES = 2026, 5
di = datetime(ANO, MES, 1).date()
df = datetime(ANO, MES + 1, 1).date()


def main() -> None:
    u = get_user_model().objects.get(username__iexact="VIVIANE")
    folha = calcular_folha_mes(ANO, MES, vendedor_id=u.id)
    vd = folha["vendedores"][0]
    r = vd["resumo"]

    print(f"=== VIVIANE maio/2026 ===")
    print(f"Liquido: R$ {float(r.get('liquido') or 0):.2f}")
    print(f"Comissao: R$ {float(r.get('comissao_total_geral') or 0):.2f}")
    print(f"Compl. sabado: R$ {float(r.get('complemento_sabado_total') or 0):.2f}")
    print("\n--- Descontos ---")
    for d in r.get("detalhes_descontos") or []:
        if "sábado" in (d.get("motivo") or "").lower() or d.get("tipo_exibicao") == "folha_adiant_sabado_cancel":
            print(f"  {d}")

    ref = r.get("info_adiantamento_origem") or {}
    print("\n--- Referencia adiantamentos ---")
    for k, v in ref.items():
        if v and (v.get("quantidade") or v.get("valor_total")):
            print(f"  {k}: {v}")

    print("\n--- As 8 vendas marcadas ---")
    for vid in IDS:
        v = Venda.objects.select_related("status_esteira", "cliente", "plano").get(pk=vid)
        st = (v.status_esteira.nome if v.status_esteira else "-")
        nome = (v.cliente.nome_razao_social or "")[:35]
        origem = origem_adiantamento_comissao_venda(v) or "-"
        ja_ant = comissao_ja_adiantada_venda(v)
        eleg_est = venda_elegivel_estorno_adiantamento_sabado(v)
        entra_est = venda_entra_estorno_adiantamento_sabado_mes(v, di, df)
        print(
            f"\n#{vid} | {nome} | {st}"
            f"\n  sab_val=R${float(v.adiantamento_sabado_valor or 0):.0f} "
            f"manual={bool(v.adiantamento_sabado_obs_manual)} "
            f"abertura={v.data_abertura}"
            f"\n  antecip={v.antecipacao_comissao} quitado={bool(v.adiantamento_sabado_quitado_em)} "
            f"flag_desc={v.flag_desc_adiantamento_sabado}"
            f"\n  origem_folha={origem} ja_adiantada={ja_ant}"
            f"\n  elegivel_estorno={eleg_est} entra_estorno_mes={entra_est}"
        )
        if entra_est:
            print(f"  -> ESTORNO: {motivo_estorno_adiantamento_sabado(v)}")

    print("\n--- Extrato (ids das 8) ---")
    extrato_ids = {linha.get("venda_id"): linha for linha in vd.get("extrato") or []}
    for vid in IDS:
        linha = extrato_ids.get(vid)
        if linha:
            print(
                f"  #{vid} extrato: val={linha.get('valor_comissao')} "
                f"tipo={linha.get('comissao_tipo')} adiantada={linha.get('adiantada')}"
            )
        else:
            print(f"  #{vid} NAO APARECE NO EXTRATO")


if __name__ == "__main__":
    main()
