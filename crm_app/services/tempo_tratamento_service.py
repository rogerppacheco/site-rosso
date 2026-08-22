"""Serviço de medição de tempo de tratamento (auditoria e esteira).

Responsável por abrir, manter (heartbeat) e encerrar sessões de tratamento
com relógio do servidor. Toda a lógica de negócio fica isolada aqui para manter
as views enxutas (padrão "skinny views / fat services").
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from crm_app.models import SessaoTratamento, Venda

logger = logging.getLogger(__name__)

MODULOS_VALIDOS = {SessaoTratamento.MODULO_AUDITORIA, SessaoTratamento.MODULO_ESTEIRA}


def normalizar_modulo(valor: str | None) -> str:
    modulo = (valor or '').strip().upper()
    return modulo if modulo in MODULOS_VALIDOS else SessaoTratamento.MODULO_AUDITORIA


def _sessoes_abertas(venda_id: int, usuario, modulo: str):
    return SessaoTratamento.objects.filter(
        venda_id=venda_id,
        usuario=usuario,
        modulo=modulo,
        finalizado_em__isnull=True,
    )


def _encerrar_queryset(queryset, motivo: str, status_resultado: str = '') -> int:
    """Encerra todas as sessões abertas de um queryset. Retorna quantas foram fechadas."""
    agora = timezone.now()
    encerradas = 0
    for sessao in queryset.select_for_update():
        _finalizar_instancia(sessao, motivo, status_resultado, agora)
        encerradas += 1
    return encerradas


def _finalizar_instancia(
    sessao: SessaoTratamento, motivo: str, status_resultado: str, agora=None
) -> None:
    if sessao.finalizado_em is not None:
        return
    agora = agora or timezone.now()
    delta = agora - sessao.iniciado_em
    duracao = max(0, int(delta.total_seconds()))
    sessao.finalizado_em = agora
    sessao.duracao_segundos = duracao
    sessao.motivo_fim = motivo
    if status_resultado:
        sessao.status_resultado = status_resultado[:120]
    sessao.save(
        update_fields=['finalizado_em', 'duracao_segundos', 'motivo_fim', 'status_resultado']
    )


@transaction.atomic
def iniciar_sessao(venda: Venda, usuario, modulo: str) -> SessaoTratamento:
    """Abre uma nova sessão de tratamento.

    Fecha sessões anteriores ainda abertas do mesmo usuário/venda/módulo como
    ABANDONO, evitando cronômetros duplicados ao retomar um tratamento.
    """
    modulo = normalizar_modulo(modulo)
    _encerrar_queryset(
        _sessoes_abertas(venda.id, usuario, modulo),
        SessaoTratamento.MOTIVO_ABANDONO,
    )
    agora = timezone.now()
    return SessaoTratamento.objects.create(
        venda=venda,
        usuario=usuario,
        modulo=modulo,
        iniciado_em=agora,
        ultimo_ping=agora,
    )


def registrar_ping(venda_id: int, usuario, modulo: str) -> SessaoTratamento | None:
    """Atualiza o heartbeat da sessão aberta mais recente. Retorna a sessão ou None."""
    modulo = normalizar_modulo(modulo)
    sessao = _sessoes_abertas(venda_id, usuario, modulo).order_by('-iniciado_em').first()
    if not sessao:
        return None
    sessao.ultimo_ping = timezone.now()
    sessao.save(update_fields=['ultimo_ping'])
    return sessao


@transaction.atomic
def encerrar_sessoes(
    venda_id: int, usuario, modulo: str, motivo: str, status_resultado: str = ''
) -> int:
    """Encerra as sessões abertas do usuário para a venda/módulo. Idempotente."""
    modulo = normalizar_modulo(modulo)
    return _encerrar_queryset(
        _sessoes_abertas(venda_id, usuario, modulo), motivo, status_resultado
    )


@transaction.atomic
def encerrar_sessoes_venda(
    venda_id: int, modulo: str, motivo: str, status_resultado: str = ''
) -> int:
    """Encerra TODAS as sessões abertas de uma venda/módulo (qualquer usuário).

    Usado quando a decisão foi tomada via backend (ex.: finalizar auditoria),
    garantindo que nenhuma sessão fique aberta mesmo em cenário multi-aba.
    """
    modulo = normalizar_modulo(modulo)
    queryset = SessaoTratamento.objects.filter(
        venda_id=venda_id, modulo=modulo, finalizado_em__isnull=True,
    )
    return _encerrar_queryset(queryset, motivo, status_resultado)


@transaction.atomic
def encerrar_sessoes_ociosas(timeout_minutos: int) -> int:
    """Fecha sessões sem heartbeat há mais que ``timeout_minutos`` (job do scheduler)."""
    if timeout_minutos <= 0:
        return 0
    limite = timezone.now() - timezone.timedelta(minutes=timeout_minutos)
    queryset = SessaoTratamento.objects.filter(
        finalizado_em__isnull=True, ultimo_ping__lt=limite,
    )
    encerradas = _encerrar_queryset(queryset, SessaoTratamento.MOTIVO_TIMEOUT)
    if encerradas:
        logger.info('Encerradas %s sessão(ões) de tratamento ociosas (timeout=%smin).',
                    encerradas, timeout_minutos)
    return encerradas
