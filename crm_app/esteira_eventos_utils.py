"""Registro de eventos da esteira de vendas (Fase 2 — timeline para gestão)."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

ORIGEM_MANUAL = 'MANUAL'
ORIGEM_OSAB = 'OSAB'
ORIGEM_SISTEMA = 'SISTEMA'

TIPO_STATUS_ESTEIRA = 'STATUS_ESTEIRA'
TIPO_MOTIVO_PENDENCIA = 'MOTIVO_PENDENCIA'
TIPO_AGENDAMENTO = 'AGENDAMENTO'
TIPO_INSTALACAO = 'INSTALACAO'
TIPO_INSTALACAO_FISICA = 'INSTALACAO_FISICA'
TIPO_MSG_CLIENTE_PENDENCIA = 'MSG_CLIENTE_PENDENCIA'


def _nome_status(status) -> str:
    if not status:
        return ''
    return str(getattr(status, 'nome', status) or '')


def _nome_motivo(motivo) -> str:
    if not motivo:
        return ''
    return str(getattr(motivo, 'nome', motivo) or '')


def _fmt_data(d) -> str:
    if d is None:
        return ''
    if hasattr(d, 'isoformat'):
        return d.isoformat()
    return str(d)


def _fmt_agendamento(data, periodo) -> str:
    d = _fmt_data(data)
    p = (periodo or '').strip()
    if d and p:
        return f'{d}|{p}'
    return d or p or ''


def _status_e_pendencia_nome(nome: str) -> bool:
    n = (nome or '').upper()
    return 'PENDEN' in n or 'PENDÊN' in n


def criar_evento_esteira(
    *,
    venda_id: int,
    tipo_evento: str,
    valor_anterior: str = '',
    valor_novo: str = '',
    origem: str,
    usuario=None,
    motivo_pendencia_id: Optional[int] = None,
):
    from crm_app.models import VendaEsteiraEvento

    if not venda_id:
        return None
    if valor_anterior == valor_novo and tipo_evento not in (TIPO_STATUS_ESTEIRA,):
        return None
    return VendaEsteiraEvento(
        venda_id=venda_id,
        tipo_evento=tipo_evento,
        valor_anterior=(valor_anterior or '')[:500],
        valor_novo=(valor_novo or '')[:500],
        origem=origem,
        usuario=usuario,
        motivo_pendencia_id=motivo_pendencia_id,
    )


def registrar_eventos_venda_esteira(venda_antes, venda_depois, origem: str, usuario=None) -> list:
    """
    Compara snapshot antes/depois e retorna instâncias de VendaEsteiraEvento (não salvas).
  """
    if not venda_depois or not getattr(venda_depois, 'id', None):
        return []

    eventos = []
    vid = venda_depois.id

    st_ant = _nome_status(getattr(venda_antes, 'status_esteira', None))
    st_nov = _nome_status(venda_depois.status_esteira)
    if st_ant != st_nov:
        ev = criar_evento_esteira(
            venda_id=vid,
            tipo_evento=TIPO_STATUS_ESTEIRA,
            valor_anterior=st_ant,
            valor_novo=st_nov,
            origem=origem,
            usuario=usuario,
        )
        if ev:
            eventos.append(ev)

    mot_ant = _nome_motivo(getattr(venda_antes, 'motivo_pendencia', None))
    mot_nov = _nome_motivo(venda_depois.motivo_pendencia)
    if mot_ant != mot_nov:
        ev = criar_evento_esteira(
            venda_id=vid,
            tipo_evento=TIPO_MOTIVO_PENDENCIA,
            valor_anterior=mot_ant,
            valor_novo=mot_nov,
            origem=origem,
            usuario=usuario,
            motivo_pendencia_id=venda_depois.motivo_pendencia_id,
        )
        if ev:
            eventos.append(ev)

    ag_ant = _fmt_agendamento(
        getattr(venda_antes, 'data_agendamento', None),
        getattr(venda_antes, 'periodo_agendamento', None),
    )
    ag_nov = _fmt_agendamento(venda_depois.data_agendamento, venda_depois.periodo_agendamento)
    if ag_ant != ag_nov:
        ev = criar_evento_esteira(
            venda_id=vid,
            tipo_evento=TIPO_AGENDAMENTO,
            valor_anterior=ag_ant,
            valor_novo=ag_nov,
            origem=origem,
            usuario=usuario,
        )
        if ev:
            eventos.append(ev)

    di_ant = _fmt_data(getattr(venda_antes, 'data_instalacao', None))
    di_nov = _fmt_data(venda_depois.data_instalacao)
    if di_ant != di_nov:
        ev = criar_evento_esteira(
            venda_id=vid,
            tipo_evento=TIPO_INSTALACAO,
            valor_anterior=di_ant,
            valor_novo=di_nov,
            origem=origem,
            usuario=usuario,
        )
        if ev:
            eventos.append(ev)

    dif_ant = _fmt_data(getattr(venda_antes, 'data_instalacao_fisica', None))
    dif_nov = _fmt_data(venda_depois.data_instalacao_fisica)
    if dif_ant != dif_nov:
        ev = criar_evento_esteira(
            venda_id=vid,
            tipo_evento=TIPO_INSTALACAO_FISICA,
            valor_anterior=dif_ant,
            valor_novo=dif_nov,
            origem=origem,
            usuario=usuario,
        )
        if ev:
            eventos.append(ev)

    return eventos


def salvar_eventos_esteira(eventos: Iterable) -> int:
    from crm_app.models import VendaEsteiraEvento

    lista = [e for e in eventos if e is not None]
    if not lista:
        return 0
    try:
        VendaEsteiraEvento.objects.bulk_create(lista, batch_size=500)
        return len(lista)
    except Exception:
        logger.exception('Erro ao gravar eventos da esteira')
        return 0


def registrar_e_salvar_eventos_venda_esteira(venda_antes, venda_depois, origem: str, usuario=None) -> int:
    eventos = registrar_eventos_venda_esteira(venda_antes, venda_depois, origem, usuario)
    return salvar_eventos_esteira(eventos)


class VendaEsteiraSnap:
    """Snapshot leve dos campos da esteira antes de mutação (ex.: import OSAB)."""

    __slots__ = (
        'status_esteira',
        'motivo_pendencia',
        'data_agendamento',
        'periodo_agendamento',
        'data_instalacao',
        'data_instalacao_fisica',
    )

    @classmethod
    def from_venda(cls, venda) -> 'VendaEsteiraSnap':
        s = cls()
        s.status_esteira = venda.status_esteira
        s.motivo_pendencia = venda.motivo_pendencia
        s.data_agendamento = venda.data_agendamento
        s.periodo_agendamento = venda.periodo_agendamento
        s.data_instalacao = venda.data_instalacao
        s.data_instalacao_fisica = venda.data_instalacao_fisica
        return s
