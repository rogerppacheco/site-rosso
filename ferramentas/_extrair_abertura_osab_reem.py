"""Extrai DATA_ABERTURA da OSAB para as 10 reemissões de ago/2026."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

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


def norm_ba(x: object) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def to_date(v: object) -> date | None:
    if pd.isna(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):
        # Excel serial (xlsb)
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def main() -> None:
    df = pd.read_excel(PATH, engine="pyxlsb", sheet_name="BASE")
    df["_ba"] = df["numero_ba"].map(norm_ba)
    sub = df[df["_ba"].isin(OSS)].copy()
    sub["DATA_ABERTURA_DT"] = sub["DATA_ABERTURA"].map(to_date)

    print(f"found={len(sub)}", flush=True)
    print("os|data_abertura_osab|situacao|nr_ordem_original", flush=True)
    by_os: dict[str, date | None] = {}
    for _, r in sub.iterrows():
        ba = norm_ba(r["numero_ba"])
        dt = r["DATA_ABERTURA_DT"]
        by_os[ba] = dt
        print(
            f"{ba}|{dt}|{r.get('SITUACAO')}|{r.get('nr_ordem_original')}",
            flush=True,
        )
    missing = [o for o in OSS if o not in by_os]
    print(f"missing={missing}", flush=True)


if __name__ == "__main__":
    main()
