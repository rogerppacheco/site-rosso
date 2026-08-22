"""
Relatório de pendências tipo CLIENTE por vendedor — imagem WhatsApp (Esteira).

Disparo automático nos horários de EsteiraVendasConfig (seg–sex).
"""
from __future__ import annotations

import base64
import io
import logging
import unicodedata
from datetime import datetime, time
from typing import Any

from django.db.models import Count
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from crm_app.esteira_config_utils import get_esteira_vendas_config
from crm_app.models import EsteiraVendasConfig, GrupoDisparo, Venda
from crm_app.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

JANELA_ATRASO_MINUTOS = 10


def _horario_para_slot(horario: time | None) -> str | None:
    if not horario:
        return None
    return f'{horario.hour:02d}:{horario.minute:02d}'


def _parse_horario_str(valor: str) -> time | None:
    texto = (valor or '').strip()
    if not texto:
        return None
    try:
        hh_str, mm_str = texto.split(':')
        hh, mm = int(hh_str), int(mm_str)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return time(hh, mm)
    except (ValueError, TypeError):
        return None
    return None


def validar_horario_relatorio(valor: Any) -> time | None:
    """Aceita HH:MM ou time para persistência na config."""
    if isinstance(valor, time):
        return valor
    if valor is None:
        return None
    return _parse_horario_str(str(valor))


def _nome_vendedor_display(username: str | None, first_name: str | None) -> str:
    nome = (first_name or '').strip() or (username or '').strip()
    return nome or '—'


def contar_pendencias_cliente_por_vendedor() -> dict[str, Any]:
    """
    Conta vendas ativas na Esteira com status PENDENTE e motivo tipo CLIENTE,
    agrupadas por vendedor em ordem alfabética.
    """
    rows = (
        Venda.objects.filter(
            ativo=True,
            status_esteira__nome__icontains='PENDEN',
            motivo_pendencia__tipo_pendencia__icontains='CLIENTE',
            vendedor__isnull=False,
        )
        .values(
            'vendedor_id',
            'vendedor__username',
            'vendedor__first_name',
        )
        .annotate(qtd=Count('id'))
        .order_by(
            Lower(Coalesce('vendedor__first_name', 'vendedor__username')),
            Lower('vendedor__username'),
        )
    )

    lista: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        qtd = int(row['qtd'] or 0)
        if qtd <= 0:
            continue
        nome = _nome_vendedor_display(row.get('vendedor__username'), row.get('vendedor__first_name'))
        lista.append({
            'vendedor_id': row['vendedor_id'],
            'nome': nome,
            'qtd': qtd,
        })
        total += qtd

    # Ordenação alfabética estável (pt-BR) após montar o display name
    lista.sort(key=lambda item: unicodedata.normalize('NFKD', item['nome']).casefold())
    return {'lista': lista, 'total': total}


def montar_caption_pendencia_cliente(
    metricas: dict[str, Any],
    *,
    slot: str,
    agora: datetime | None = None,
) -> str:
    agora = agora or timezone.localtime(timezone.now())
    data_str = agora.strftime('%d/%m/%Y')
    total = int(metricas.get('total') or 0)
    linhas = [
        '📋 Pendências CLIENTE — Esteira',
        f'📅 {data_str} · {slot}',
        '',
        f'Total: {total} pedido(s)',
        '',
    ]
    lista = metricas.get('lista') or []
    if not lista:
        linhas.append('Nenhuma pendência CLIENTE no momento.')
    else:
        for item in lista:
            linhas.append(f"{item['nome']} — {item['qtd']}")
        linhas.append('')
        linhas.append('Prioridade: resolver pendência com o cliente.')
    return '\n'.join(linhas)


def gerar_imagem_pendencia_cliente_b64(
    metricas: dict[str, Any],
    *,
    slot: str,
    agora: datetime | None = None,
) -> str | None:
    """Gera PNG base64 (data URL) com a lista alfabética de vendedores."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error('Pillow não disponível para gerar imagem de pendência cliente.')
        return None

    agora = agora or timezone.localtime(timezone.now())
    lista = metricas.get('lista') or []
    total = int(metricas.get('total') or 0)
    data_str = agora.strftime('%d/%m/%Y')

    svc = WhatsAppService()
    f_titulo = svc._font_performance('arial', 36)
    f_sub = svc._font_performance('arial', 22)
    f_texto = svc._font_performance('arial', 26)
    f_bold = svc._font_performance('arial', 26)

    H_TITULO = 70
    H_SUB = 36
    H_HEADER = 44
    H_LINHA = 42
    H_RODAPE = 28
    W = 720
    qtd_linhas = max(len(lista), 1) + 1  # dados (ou vazio) + total
    H = H_TITULO + H_SUB + H_HEADER + (qtd_linhas * H_LINHA) + H_RODAPE + 24

    cor_fundo = (255, 255, 255)
    cor_azul_header = (78, 115, 223)
    cor_azul_total = (44, 62, 80)
    cor_texto = (33, 37, 41)
    cor_muted = (108, 117, 125)
    cor_borda = (227, 230, 240)
    cor_zebra = (248, 249, 250)

    img = Image.new('RGB', (W, H), color=cor_fundo)
    d = ImageDraw.Draw(img)

    d.text((W / 2, H_TITULO // 2), 'Pendências CLIENTE — Esteira', fill=cor_texto, anchor='mm', font=f_titulo)
    d.text(
        (W / 2, H_TITULO + H_SUB // 2),
        f'{data_str} · corte {slot}',
        fill=cor_muted,
        anchor='mm',
        font=f_sub,
    )

    y = H_TITULO + H_SUB
    col_x = [36, W - 48]
    d.rectangle([(20, y), (W - 20, y + H_HEADER)], fill=cor_azul_header)
    d.text((col_x[0], y + H_HEADER // 2), 'Vendedor', fill='white', anchor='lm', font=f_bold)
    d.text((col_x[1], y + H_HEADER // 2), 'Qtd', fill='white', anchor='rm', font=f_bold)
    y += H_HEADER

    if not lista:
        d.rectangle([(20, y), (W - 20, y + H_LINHA)], fill=cor_zebra)
        d.text((W / 2, y + H_LINHA // 2), 'Nenhuma pendência CLIENTE', fill=cor_muted, anchor='mm', font=f_texto)
        y += H_LINHA
    else:
        for i, item in enumerate(lista):
            bg = cor_zebra if i % 2 else cor_fundo
            d.rectangle([(20, y), (W - 20, y + H_LINHA)], fill=bg)
            d.line([(20, y + H_LINHA), (W - 20, y + H_LINHA)], fill=cor_borda)
            nome = str(item.get('nome') or '—')[:32]
            qtd = str(item.get('qtd') or 0)
            d.text((col_x[0], y + H_LINHA // 2), nome, fill=cor_texto, anchor='lm', font=f_texto)
            d.text((col_x[1], y + H_LINHA // 2), qtd, fill=cor_texto, anchor='rm', font=f_bold)
            y += H_LINHA

    d.rectangle([(20, y), (W - 20, y + H_LINHA)], fill=cor_azul_total)
    d.text((col_x[0], y + H_LINHA // 2), 'TOTAL', fill='white', anchor='lm', font=f_bold)
    d.text((col_x[1], y + H_LINHA // 2), str(total), fill='white', anchor='rm', font=f_bold)

    buffered = io.BytesIO()
    img.save(buffered, format='PNG')
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{img_str}'


def _horarios_configurados(config: EsteiraVendasConfig) -> list[str]:
    slots: list[str] = []
    for horario in (
        config.relatorio_pendencia_cliente_horario_1,
        config.relatorio_pendencia_cliente_horario_2,
    ):
        slot = _horario_para_slot(horario)
        if slot and slot not in slots:
            slots.append(slot)
    return sorted(slots)


def _slots_enviados_hoje(config: EsteiraVendasConfig, hoje_str: str) -> set[str]:
    controle = config.relatorio_pendencia_cliente_controle_disparos or {}
    if controle.get('date') != hoje_str:
        return set()
    return {str(s) for s in (controle.get('slots') or [])}


def _marcar_slot_enviado(config: EsteiraVendasConfig, hoje_str: str, slot: str) -> None:
    controle = dict(config.relatorio_pendencia_cliente_controle_disparos or {})
    if controle.get('date') != hoje_str:
        controle = {'date': hoje_str, 'slots': []}
    slots = list(controle.get('slots') or [])
    if slot not in slots:
        slots.append(slot)
    controle['date'] = hoje_str
    controle['slots'] = slots
    config.relatorio_pendencia_cliente_controle_disparos = controle
    config.save(update_fields=['relatorio_pendencia_cliente_controle_disparos'])


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


def obter_grupos_destino(config: EsteiraVendasConfig | None = None) -> list[GrupoDisparo]:
    config = config or get_esteira_vendas_config()
    if not config.pk:
        return []
    return list(
        config.relatorio_pendencia_cliente_grupos.filter(ativo=True)
        .exclude(chat_id='')
        .order_by('nome')
    )


def aplicar_grupos_destino(config: EsteiraVendasConfig, grupo_ids: list[Any] | None) -> None:
    if grupo_ids is None:
        return
    ids_limpos: list[int] = []
    for raw in grupo_ids:
        if raw is None or raw == '':
            continue
        try:
            ids_limpos.append(int(raw))
        except (TypeError, ValueError):
            continue
    grupos = list(GrupoDisparo.objects.filter(id__in=ids_limpos, ativo=True).order_by('nome'))
    by_id = {g.id: g for g in grupos}
    ordenados = [by_id[i] for i in ids_limpos if i in by_id]
    config.relatorio_pendencia_cliente_grupos.set(ordenados)


def serializar_config_relatorio(config: EsteiraVendasConfig) -> dict[str, Any]:
    grupos = obter_grupos_destino(config)
    grupo_ids = [g.id for g in grupos]
    return {
        'relatorio_pendencia_cliente_ativo': bool(config.relatorio_pendencia_cliente_ativo),
        'relatorio_pendencia_cliente_horario_1': (
            config.relatorio_pendencia_cliente_horario_1.strftime('%H:%M')
            if config.relatorio_pendencia_cliente_horario_1
            else '12:00'
        ),
        'relatorio_pendencia_cliente_horario_2': (
            config.relatorio_pendencia_cliente_horario_2.strftime('%H:%M')
            if config.relatorio_pendencia_cliente_horario_2
            else '18:00'
        ),
        'grupo_ids': grupo_ids,
        'grupos_destino': [
            {'id': g.id, 'nome': g.nome, 'chat_id': g.chat_id} for g in grupos
        ],
    }


def enviar_relatorio_pendencia_cliente(
    config: EsteiraVendasConfig,
    slot: str,
    *,
    agora: datetime | None = None,
    marcar_controle: bool = True,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Gera imagem + caption e envia aos grupos configurados.

    Returns:
        (ok, mensagem, detalhe) onde detalhe inclui enviados/erros/total.
    """
    agora = agora or timezone.localtime(timezone.now())
    grupos = obter_grupos_destino(config)
    if not grupos:
        return False, 'Nenhum grupo WhatsApp configurado.', {'enviados': 0, 'erros': [], 'total': 0}

    metricas = contar_pendencias_cliente_por_vendedor()
    img_b64 = gerar_imagem_pendencia_cliente_b64(metricas, slot=slot, agora=agora)
    if not img_b64:
        return False, 'Falha ao gerar a imagem.', {'enviados': 0, 'erros': [], 'total': 0}

    caption = montar_caption_pendencia_cliente(metricas, slot=slot, agora=agora)
    svc = WhatsAppService()
    enviados = 0
    erros: list[str] = []
    for grupo in grupos:
        try:
            resp = svc.enviar_imagem_b64(grupo.chat_id, img_b64, caption=caption)
            if resp:
                enviados += 1
            else:
                erros.append(f'{grupo.nome}: provedor não confirmou')
        except Exception as exc:  # noqa: BLE001 — isolamento por destino
            erros.append(f'{grupo.nome}: {str(exc)[:80]}')

    if enviados == 0:
        return False, '; '.join(erros[:3]) or 'Falha no envio WhatsApp.', {
            'enviados': 0,
            'erros': erros,
            'total': len(grupos),
            'metricas': metricas,
        }

    if marcar_controle:
        _marcar_slot_enviado(config, agora.strftime('%Y-%m-%d'), slot)

    logger.info(
        'Relatório pendência CLIENTE enviado (slot %s, total=%s, grupos=%s/%s)',
        slot,
        metricas['total'],
        enviados,
        len(grupos),
    )
    return True, 'Enviado.', {
        'enviados': enviados,
        'erros': erros,
        'total': len(grupos),
        'metricas': metricas,
    }


def processar_envio_relatorio_pendencia_cliente() -> None:
    """Verifica horários e dispara relatório (chamado pelo scheduler a cada minuto)."""
    agora = timezone.localtime(timezone.now())
    if agora.weekday() > 4:
        return

    config = get_esteira_vendas_config()
    if not config.relatorio_pendencia_cliente_ativo:
        return

    if not obter_grupos_destino(config):
        logger.debug('Relatório pendência CLIENTE: ativo mas sem grupos — ignorando.')
        return

    hoje_str = agora.strftime('%Y-%m-%d')
    enviados = _slots_enviados_hoje(config, hoje_str)
    for slot in _horarios_configurados(config):
        if not _slot_disponivel_agora(agora, slot, enviados):
            continue
        enviar_relatorio_pendencia_cliente(config, slot, agora=agora)
