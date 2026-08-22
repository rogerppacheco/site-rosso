"""Corrige Venda.data_abertura das reemissões com DATA_ABERTURA da OSAB (PEDIDO=O.S.)."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import django
import pandas as pd

PATH = Path(r"c:\Users\rogge\Downloads\MG (1).xlsb")
OSS = [
    "10414358",
    "10375236",
    "10396320",
    "10481041",
    "10269250",
    "10199105",
    "10264232",
    "10392328",
    "10290065",
    "10504736",
]


def norm(x: object) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def to_datetime(v: object) -> datetime | None:
    if pd.isna(v):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    if isinstance(v, (int, float)):
        return datetime(1899, 12, 30) + timedelta(days=float(v))
    try:
        ts = pd.to_datetime(v)
        return ts.to_pydatetime()
    except Exception:
        return None


def load_map() -> dict[str, datetime]:
    df = pd.read_excel(PATH, engine="pyxlsb", sheet_name="BASE")
    df["_pedido"] = df["PEDIDO"].map(norm)
    sub = df[df["_pedido"].isin(OSS)].copy()
    out: dict[str, datetime] = {}
    print("pedido|data_abertura_osab|situacao|numero_ba", flush=True)
    for _, r in sub.iterrows():
        p = norm(r["PEDIDO"])
        dt = to_datetime(r["DATA_ABERTURA"])
        if not p or not dt:
            continue
        out[p] = dt
        print(
            f"{p}|{dt.isoformat(sep=' ', timespec='seconds')}|{r.get('SITUACAO')}|{norm(r.get('numero_ba'))}",
            flush=True,
        )
    missing = [o for o in OSS if o not in out]
    print(f"mapped={len(out)} missing={missing}", flush=True)
    return out


def main() -> None:
    dry = "--apply" not in sys.argv
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
    django.setup()

    from crm_app.models import Venda
    from crm_app.osab_datetime_utils import osab_datetime_to_aware
    from crm_app.esteira_gestao_aproveitamento_api import _montar_resumo_mes
    from datetime import date as date_cls

    mapping = load_map()
    print(f"dry_run={dry}", flush=True)

    updated = 0
    for os_num, dt_naive in mapping.items():
        v = (
            Venda.objects.filter(ordem_servico=os_num, reemissao=True, ativo=True)
            .order_by("-id")
            .first()
        )
        if not v:
            print(f"SKIP sem venda reem OS={os_num}", flush=True)
            continue
        old = v.data_abertura
        new_dt = osab_datetime_to_aware(dt_naive)
        print(
            f"venda={v.id} OS={os_num} "
            f"{old.date() if old else None} -> {new_dt.date() if new_dt else None}",
            flush=True,
        )
        if dry or new_dt is None:
            continue
        v.data_abertura = new_dt
        v.save(update_fields=["data_abertura"])
        updated += 1
        print("  OK", flush=True)

    print(f"updated={updated}", flush=True)

    # Conferência KPI agosto
    ini, fim = date_cls(2026, 8, 1), date_cls(2026, 8, 31)
    base = (
        Venda.objects.filter(ativo=True, status_tratamento__nome__iexact="CADASTRADA")
        .exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico="")
    )
    com = base.filter(data_abertura__date__gte=ini, data_abertura__date__lte=fim).count()
    sem = (
        base.filter(reemissao=False, data_abertura__date__gte=ini, data_abertura__date__lte=fim)
        .count()
    )
    reem_ago = (
        base.filter(reemissao=True, data_abertura__date__gte=ini, data_abertura__date__lte=fim)
        .count()
    )
    print(
        f"CHECK ago COM_REEM={com} SEM_REEM={sem} REEM_EM_AGO={reem_ago}",
        flush=True,
    )


if __name__ == "__main__":
    main()
