"""
Relatório diário de ativados e esteira de auditoria enviado ao GC via WhatsApp.

Disparo automático nos horários configurados em AnteciparInstalacaoConfig (seg-sex).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from django.db.models import Count
from django.utils import timezone

from crm_app.models import AnteciparInstalacaoConfig, Venda
from crm_app.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

JANELA_ATRASO_MINUTOS = 10
MAX_HORARIOS_RELATORIO = 12
HORARIOS_RELATORIO_PADRAO = ['17:20', '18:00']


def _get_config() -> AnteciparInstalacaoConfig:
    config = AnteciparInstalacaoConfig.objects.first()
    if not config:
        config = AnteciparInstalacaoConfig.objects.create(telefone_gc='', nome_gc='')
    return config


def _horario_para_slot(horario: time | None) -> str | None:
    if not horario:
        return None
    return f"{horario.hour:02d}:{horario.minute:02d}"


def _parse_horario_str(valor: str) -> time | None:
    texto = (valor or '').strip()
    if not texto:
        return None
    try:
        partes = texto.split(':')
        hh, mm = int(partes[0]), int(partes[1])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return time(hh, mm)
    except (ValueError, TypeError, IndexError):
        return None
    return None


def _primeiro_nome(nome_completo: str) -> str:
    partes = (nome_completo or '').strip().split()
    return partes[0] if partes else 'GC'


def _saudacao_horario(agora: datetime) -> str:
    return 'boa tarde' if agora.hour >= 12 else 'bom dia'


def _formatar_rotulo_status(nome: str) -> str:
    """Exibe status legível sem caixa alta forçada."""
    texto = (nome or '').strip()
    if not texto:
        return '—'
    return texto.title()


def contar_ativados(data_ref: date) -> int:
    """Vendas com O.S. aberta no dia e status CADASTRADA (regra Performance Hoje)."""
    return (
        Venda.objects.filter(
            ativo=True,
            reemissao=False,
            ordem_servico__isnull=False,
            status_tratamento__nome__iexact='CADASTRADA',
            data_abertura__date=data_ref,
        )
        .exclude(ordem_servico='')
        .count()
    )


def contagem_esteira_auditoria(data_ref: date) -> list[dict[str, Any]]:
    """
    Vendas criadas no dia ainda na fila de auditoria, agrupadas por status de tratamento.
    """
    rows = (
        Venda.objects.filter(
            ativo=True,
            data_criacao__date=data_ref,
            status_tratamento__isnull=False,
            status_esteira__isnull=True,
        )
        .exclude(status_tratamento__estado__iexact='FECHADO')
        .values('status_tratamento__nome')
        .annotate(qtd=Count('id'))
        .order_by('status_tratamento__nome')
    )
    return [
        {
            'status': row['status_tratamento__nome'] or '—',
            'qtd': row['qtd'],
        }
        for row in rows
        if row['qtd'] > 0
    ]


def calcular_metricas(data_ref: date) -> dict[str, Any]:
    return {
        'data_ref': data_ref,
        'ativados': contar_ativados(data_ref),
        'esteira': contagem_esteira_auditoria(data_ref),
    }


def montar_mensagem_relatorio_esteira_gc(
    config: AnteciparInstalacaoConfig,
    metricas: dict[str, Any],
    *,
    slot: str,
    agora: datetime | None = None,
) -> str:
    agora = agora or timezone.localtime(timezone.now())
    nome = _primeiro_nome(config.nome_gc or '')
    saudacao = _saudacao_horario(agora)
    linhas = [
        f"{nome}, {saudacao}",
    ]
    horarios = listar_horarios_relatorio(config)
    if horarios and slot != horarios[0]:
        linhas.append(f"Atualização {slot} — segue resultado e esteira de vendas:")
    else:
        linhas.append("Segue resultado e esteira de vendas:")
    linhas.append("")
    linhas.append(f"Ativados: {metricas['ativados']}")
    linhas.append("")
    linhas.append("Esteira:")
    esteira = metricas.get('esteira') or []
    if not esteira:
        linhas.append("(nenhuma venda pendente na auditoria hoje)")
    else:
        for item in esteira:
            rotulo = _formatar_rotulo_status(item['status'])
            linhas.append(f"{rotulo}: {item['qtd']}")
    return '\n'.join(linhas)


def normalizar_horarios_relatorio(valor: Any) -> list[str]:
    """Aceita lista, string CSV ou time; devolve HH:MM únicos, ordenados e limitados."""
    if valor is None or valor == '':
        itens: list[Any] = []
    elif isinstance(valor, list):
        itens = valor
    else:
        texto = str(valor).replace(';', ',').replace('\n', ',')
        itens = [p.strip() for p in texto.split(',') if p.strip()]

    slots: list[str] = []
    for item in itens:
        horario = validar_horario_relatorio(item)
        slot = _horario_para_slot(horario) if horario else None
        if slot and slot not in slots:
            slots.append(slot)
        if len(slots) >= MAX_HORARIOS_RELATORIO:
            break
    return sorted(slots)


def listar_horarios_relatorio(config: AnteciparInstalacaoConfig) -> list[str]:
    """Horários efetivos do relatório: JSON primeiro; fallback nos dois campos legados."""
    slots = normalizar_horarios_relatorio(config.relatorio_esteira_horarios)
    if slots:
        return slots
    legado: list[str] = []
    for horario in (config.relatorio_esteira_horario_1, config.relatorio_esteira_horario_2):
        slot = _horario_para_slot(horario)
        if slot and slot not in legado:
            legado.append(slot)
    return sorted(legado) or list(HORARIOS_RELATORIO_PADRAO)


def aplicar_horarios_relatorio(config: AnteciparInstalacaoConfig, valor: Any) -> list[str]:
    """Persiste a lista no JSON e espelha os dois primeiros nos campos TimeField legados."""
    slots = normalizar_horarios_relatorio(valor)
    if not slots:
        slots = list(HORARIOS_RELATORIO_PADRAO)
    config.relatorio_esteira_horarios = slots
    h1 = validar_horario_relatorio(slots[0])
    h2 = validar_horario_relatorio(slots[1] if len(slots) > 1 else slots[0])
    if h1:
        config.relatorio_esteira_horario_1 = h1
    if h2:
        config.relatorio_esteira_horario_2 = h2
    return slots


def serializar_horarios_relatorio_config(config: AnteciparInstalacaoConfig) -> dict[str, Any]:
    horarios = listar_horarios_relatorio(config)
    return {
        'relatorio_esteira_horarios': horarios,
        'relatorio_esteira_horario_1': horarios[0] if horarios else HORARIOS_RELATORIO_PADRAO[0],
        'relatorio_esteira_horario_2': (
            horarios[1] if len(horarios) > 1 else (horarios[0] if horarios else HORARIOS_RELATORIO_PADRAO[1])
        ),
    }


def _horarios_configurados(config: AnteciparInstalacaoConfig) -> list[str]:
    return listar_horarios_relatorio(config)


def _slots_enviados_hoje(config: AnteciparInstalacaoConfig, hoje_str: str) -> set[str]:
    controle = config.relatorio_esteira_controle_disparos or {}
    if controle.get('date') != hoje_str:
        return set()
    return {str(s) for s in (controle.get('slots') or [])}


def _marcar_slot_enviado(config: AnteciparInstalacaoConfig, hoje_str: str, slot: str) -> None:
    controle = dict(config.relatorio_esteira_controle_disparos or {})
    if controle.get('date') != hoje_str:
        controle = {'date': hoje_str, 'slots': []}
    slots = list(controle.get('slots') or [])
    if slot not in slots:
        slots.append(slot)
    controle['date'] = hoje_str
    controle['slots'] = slots
    config.relatorio_esteira_controle_disparos = controle
    config.save(update_fields=['relatorio_esteira_controle_disparos'])


def _slot_disponivel_agora(agora: datetime, slot: str, enviados: set[str]) -> bool:
    if slot in enviados:
        return False
    try:
        hh_str, mm_str = slot.split(':')
        alvo_min = int(hh_str) * 60 + int(mm_str)
    except (ValueError, TypeError):
        return False
    agora_min = agora.hour * 60 + agora.minute
    atraso = agora_min - alvo_min
    return 0 <= atraso <= JANELA_ATRASO_MINUTOS


def enviar_relatorio_esteira_gc(
    config: AnteciparInstalacaoConfig,
    slot: str,
    *,
    agora: datetime | None = None,
) -> tuple[bool, str]:
    agora = agora or timezone.localtime(timezone.now())
    telefone = (config.telefone_gc or '').strip()
    if not telefone:
        return False, 'Telefone do GC não configurado.'

    metricas = calcular_metricas(agora.date())
    mensagem = montar_mensagem_relatorio_esteira_gc(config, metricas, slot=slot, agora=agora)
    svc = WhatsAppService()
    ok, resp = svc.enviar_mensagem_texto(telefone, mensagem)
    if ok:
        _marcar_slot_enviado(config, agora.strftime('%Y-%m-%d'), slot)
        logger.info(
            "Relatório esteira GC enviado para %s (slot %s, ativados=%s)",
            telefone,
            slot,
            metricas['ativados'],
        )
        return True, 'Enviado.'
    logger.warning("Falha ao enviar relatório esteira GC (%s): %s", slot, resp)
    return False, str(resp or 'Falha no envio WhatsApp.')


def processar_envio_relatorio_esteira_gc() -> None:
    """Verifica horários e dispara relatório ao GC (chamado pelo scheduler a cada minuto)."""
    agora = timezone.localtime(timezone.now())
    if agora.weekday() > 4:
        return

    config = _get_config()
    if not config.relatorio_esteira_gc_ativo:
        return

    telefone = (config.telefone_gc or '').strip()
    if not telefone:
        logger.debug("Relatório esteira GC: ativo mas telefone_gc vazio — ignorando.")
        return

    hoje_str = agora.strftime('%Y-%m-%d')
    enviados = _slots_enviados_hoje(config, hoje_str)
    for slot in _horarios_configurados(config):
        if not _slot_disponivel_agora(agora, slot, enviados):
            continue
        enviar_relatorio_esteira_gc(config, slot, agora=agora)


def validar_horario_relatorio(valor: Any) -> time | None:
    """Aceita HH:MM ou time para persistência na config."""
    if isinstance(valor, time):
        return valor
    if valor is None:
        return None
    return _parse_horario_str(str(valor))
