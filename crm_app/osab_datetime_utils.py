"""Parsing e normalização de datetime para importação OSAB."""

from __future__ import annotations

import datetime as dt_sys
import re
from typing import Optional

import pandas as pd
from django.utils import timezone


def parse_osab_datetime(val) -> Optional[dt_sys.datetime]:
    """
    Converte valor da planilha OSAB (texto, serial Excel ou datetime) em datetime naive local.
    Preserva hora em serial Excel (parte fracionária) e em textos DD/MM/AAAA HH:MM:SS.
    """
    if val is None or val == "":
        return None
    if isinstance(val, float) and pd.isna(val):
        return None

    if isinstance(val, pd.Timestamp):
        val = val.to_pydatetime()

    dt: Optional[dt_sys.datetime] = None

    if isinstance(val, dt_sys.datetime):
        dt = val.replace(tzinfo=None) if val.tzinfo else val
    elif isinstance(val, dt_sys.date):
        dt = dt_sys.datetime.combine(val, dt_sys.time.min)
    elif isinstance(val, (float, int)):
        serial = float(val)
        if serial <= 0:
            return None
        dt = dt_sys.datetime(1899, 12, 30) + dt_sys.timedelta(days=serial)
    else:
        s_val = str(val).strip()
        if not s_val or s_val.upper() in ("NAN", "NONE", "NAT"):
            return None

        match_br = re.search(
            r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
            s_val,
        )
        if match_br:
            d, m, y, hh, mm, ss = match_br.groups()
            try:
                dt = dt_sys.datetime(
                    int(y),
                    int(m),
                    int(d),
                    int(hh or 0),
                    int(mm or 0),
                    int(ss or 0),
                )
            except ValueError:
                return None
        else:
            match_iso = re.search(
                r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2}))?)?",
                s_val,
            )
            if match_iso:
                y, m, d, hh, mm, ss = match_iso.groups()
                try:
                    dt = dt_sys.datetime(
                        int(y),
                        int(m),
                        int(d),
                        int(hh or 0),
                        int(mm or 0),
                        int(ss or 0),
                    )
                except ValueError:
                    return None

    if dt is None or dt.year < 2000:
        return None
    return dt


def osab_datetime_to_aware(val) -> Optional[dt_sys.datetime]:
    """Datetime OSAB (naive, horário local BR) → aware no fuso do Django."""
    if val is None:
        return None
    if isinstance(val, dt_sys.date) and not isinstance(val, dt_sys.datetime):
        val = dt_sys.datetime.combine(val, dt_sys.time.min)
    if timezone.is_aware(val):
        return val
    return timezone.make_aware(val, timezone.get_current_timezone())


def osab_datetimes_differ(
    crm_val,
    osab_val,
    *,
    tolerance_seconds: int = 0,
) -> bool:
    """True se CRM e OSAB divergem (compara instante no fuso local)."""
    a = osab_datetime_to_aware(crm_val)
    b = osab_datetime_to_aware(osab_val)
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    a_local = timezone.localtime(a)
    b_local = timezone.localtime(b)
    if tolerance_seconds <= 0:
        return a_local.replace(tzinfo=None) != b_local.replace(tzinfo=None)
    return abs((a_local - b_local).total_seconds()) > tolerance_seconds


def format_osab_datetime_local(val) -> str:
    aware = osab_datetime_to_aware(val)
    if not aware:
        return "-"
    return timezone.localtime(aware).strftime("%Y-%m-%d %H:%M:%S")
