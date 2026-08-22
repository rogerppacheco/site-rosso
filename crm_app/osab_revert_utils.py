"""Snapshot e reversão de alterações de vendas feitas por importação OSAB."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime


CAMPOS_FK_REVERSAO = (
    'status_esteira_id',
    'status_tratamento_id',
    'motivo_pendencia_id',
    'forma_pagamento_id',
)

CAMPOS_DATA_REVERSAO = (
    'data_abertura',
    'data_agendamento',
    'data_instalacao',
)


def _serialize_dt(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return value.isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def serializar_venda_snapshot_osab(venda) -> dict[str, Any]:
    """Estado da venda antes de mutação pela importação OSAB."""
    return {
        'status_esteira_id': venda.status_esteira_id,
        'status_tratamento_id': venda.status_tratamento_id,
        'motivo_pendencia_id': venda.motivo_pendencia_id,
        'forma_pagamento_id': venda.forma_pagamento_id,
        'data_abertura': _serialize_dt(venda.data_abertura),
        'data_agendamento': _serialize_dt(venda.data_agendamento),
        'data_instalacao': _serialize_dt(venda.data_instalacao),
    }


def _parse_data_abertura(raw: Optional[str]):
    if not raw:
        return None
    dt = parse_datetime(raw)
    if dt:
        return dt
    d = parse_date(raw)
    if d:
        return datetime.combine(d, datetime.min.time())
    return None


def _parse_data_campo(raw: Optional[str]):
    if not raw:
        return None
    d = parse_date(raw)
    if d:
        return d
    dt = parse_datetime(raw)
    if dt:
        return dt.date()
    return None


def aplicar_snapshot_venda_osab(venda, valores: dict[str, Any]) -> list[str]:
    """
    Restaura campos da venda a partir do snapshot.
    Retorna lista de nomes de campos alterados.
    """
    alterados = []

    for campo in CAMPOS_FK_REVERSAO:
        novo = valores.get(campo)
        if getattr(venda, campo) != novo:
            setattr(venda, campo, novo)
            alterados.append(campo.replace('_id', ''))

    mapping_data = {
        'data_abertura': _parse_data_abertura,
        'data_agendamento': _parse_data_campo,
        'data_instalacao': _parse_data_campo,
    }
    for campo, parser in mapping_data.items():
        novo = parser(valores.get(campo))
        atual = getattr(venda, campo)
        if atual != novo:
            setattr(venda, campo, novo)
            alterados.append(campo)

    return alterados
