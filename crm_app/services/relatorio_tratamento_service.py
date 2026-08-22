"""Relatório diário de tempo de tratamento (auditoria e esteira) via WhatsApp.

Agrega as sessões finalizadas no dia por módulo e usuário, calcula tempo médio,
mediana e outliers, monta a mensagem e envia à diretoria. É disparado pelo
scheduler no horário configurado (seg-sex).
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime
from typing import Any

from django.utils import timezone

from crm_app.models import RelatorioTratamentoConfig, SessaoTratamento
from crm_app.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

JANELA_ATRASO_MINUTOS = 15

_MODULO_LABEL = {
    SessaoTratamento.MODULO_AUDITORIA: 'AUDITORIA',
    SessaoTratamento.MODULO_ESTEIRA: 'ESTEIRA',
}


def get_config() -> RelatorioTratamentoConfig:
    config = RelatorioTratamentoConfig.objects.first()
    if not config:
        config = RelatorioTratamentoConfig.objects.create()
    return config


def _fmt_duracao(segundos: float | int | None) -> str:
    if not segundos or segundos < 0:
        return '0s'
    total = int(round(segundos))
    horas, resto = divmod(total, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f'{horas}h{minutos:02d}m'
    if minutos:
        return f'{minutos}m{seg:02d}s'
    return f'{seg}s'


def _nome_usuario(usuario) -> str:
    if not usuario:
        return 'Sem usuário'
    nome = (usuario.get_full_name() or '').strip() if hasattr(usuario, 'get_full_name') else ''
    return nome or getattr(usuario, 'username', None) or f'Usuário #{getattr(usuario, "id", "?")}'


def _primeiro_nome(nome: str) -> str:
    partes = (nome or '').strip().split()
    return partes[0] if partes else nome


def calcular_metricas_dia(data_ref: date, limite_outlier_minutos: int = 15) -> dict[str, Any]:
    """Agrega sessões produtivas finalizadas no dia por módulo e usuário."""
    limite_outlier_seg = max(0, int(limite_outlier_minutos)) * 60
    sessoes = (
        SessaoTratamento.objects.filter(
            iniciado_em__date=data_ref,
            finalizado_em__isnull=False,
            motivo_fim__in=SessaoTratamento.MOTIVOS_PRODUTIVOS,
            duracao_segundos__isnull=False,
        )
        .select_related('usuario')
    )

    modulos: dict[str, dict[int, dict[str, Any]]] = {}
    for sessao in sessoes:
        modulo = sessao.modulo
        uid = sessao.usuario_id or 0
        bucket = modulos.setdefault(modulo, {})
        registro = bucket.setdefault(
            uid,
            {'usuario': sessao.usuario, 'duracoes': [], 'outliers': 0},
        )
        registro['duracoes'].append(sessao.duracao_segundos)
        if limite_outlier_seg and sessao.duracao_segundos > limite_outlier_seg:
            registro['outliers'] += 1

    resultado: dict[str, Any] = {'data_ref': data_ref, 'modulos': {}, 'total_geral': {}}
    todas_duracoes: list[int] = []

    for modulo, usuarios in modulos.items():
        linhas = []
        duracoes_modulo: list[int] = []
        outliers_modulo = 0
        for registro in usuarios.values():
            duracoes = registro['duracoes']
            duracoes_modulo.extend(duracoes)
            outliers_modulo += registro['outliers']
            linhas.append({
                'nome': _nome_usuario(registro['usuario']),
                'qtd': len(duracoes),
                'media': statistics.mean(duracoes) if duracoes else 0,
                'mediana': statistics.median(duracoes) if duracoes else 0,
                'maximo': max(duracoes) if duracoes else 0,
                'total': sum(duracoes),
                'outliers': registro['outliers'],
            })
        linhas.sort(key=lambda item: item['qtd'], reverse=True)
        todas_duracoes.extend(duracoes_modulo)
        resultado['modulos'][modulo] = {
            'linhas': linhas,
            'qtd': len(duracoes_modulo),
            'media': statistics.mean(duracoes_modulo) if duracoes_modulo else 0,
            'mediana': statistics.median(duracoes_modulo) if duracoes_modulo else 0,
            'outliers': outliers_modulo,
        }

    resultado['total_geral'] = {
        'qtd': len(todas_duracoes),
        'media': statistics.mean(todas_duracoes) if todas_duracoes else 0,
        'mediana': statistics.median(todas_duracoes) if todas_duracoes else 0,
    }
    return resultado


def montar_mensagem(
    config: RelatorioTratamentoConfig,
    metricas: dict[str, Any],
    *,
    agora: datetime | None = None,
) -> str:
    agora = agora or timezone.localtime(timezone.now())
    data_ref: date = metricas['data_ref']
    linhas = [f'📊 *Tempo de tratamento — {data_ref.strftime("%d/%m/%Y")}*', '']

    ordem = []
    if config.incluir_auditoria:
        ordem.append(SessaoTratamento.MODULO_AUDITORIA)
    if config.incluir_esteira:
        ordem.append(SessaoTratamento.MODULO_ESTEIRA)

    houve_dados = False
    for modulo in ordem:
        dados = metricas['modulos'].get(modulo)
        linhas.append(f'*{_MODULO_LABEL.get(modulo, modulo)}*')
        if not dados or not dados['linhas']:
            linhas.append('• (sem tratamentos hoje)')
            linhas.append('')
            continue
        houve_dados = True
        for item in dados['linhas']:
            sufixo_outlier = f' | >{config.limite_outlier_minutos}min: {item["outliers"]}' if item['outliers'] else ''
            linhas.append(
                f'• {_primeiro_nome(item["nome"])}: {item["qtd"]} tratadas | '
                f'méd. {_fmt_duracao(item["media"])} | mediana {_fmt_duracao(item["mediana"])} | '
                f'máx. {_fmt_duracao(item["maximo"])}{sufixo_outlier}'
            )
        linhas.append(
            f'  ↳ Subtotal: {dados["qtd"]} | méd. {_fmt_duracao(dados["media"])} | '
            f'mediana {_fmt_duracao(dados["mediana"])}'
        )
        linhas.append('')

    total = metricas['total_geral']
    if houve_dados:
        linhas.append(
            f'*Equipe:* {total["qtd"]} tratadas | méd. {_fmt_duracao(total["media"])} | '
            f'mediana {_fmt_duracao(total["mediana"])}'
        )
    else:
        linhas.append('_Nenhum tratamento registrado hoje._')

    linhas.append('')
    linhas.append('_Tempos consideram apenas sessões com decisão (aprovado/reprovado/cadastrado/salvo)._')
    return '\n'.join(linhas)


def gerar_relatorio(data_ref: date | None = None, config: RelatorioTratamentoConfig | None = None) -> dict[str, Any]:
    """Retorna métricas + mensagem para preview/painel (sem enviar)."""
    config = config or get_config()
    data_ref = data_ref or timezone.localtime(timezone.now()).date()
    metricas = calcular_metricas_dia(data_ref, config.limite_outlier_minutos)
    mensagem = montar_mensagem(config, metricas)
    return {'metricas': metricas, 'mensagem': mensagem}


def enviar_relatorio(
    config: RelatorioTratamentoConfig | None = None,
    *,
    data_ref: date | None = None,
    agora: datetime | None = None,
) -> tuple[bool, str]:
    config = config or get_config()
    destino = (config.destino_telefone or '').strip()
    if not destino:
        return False, 'Destino do relatório não configurado.'

    agora = agora or timezone.localtime(timezone.now())
    data_ref = data_ref or agora.date()
    metricas = calcular_metricas_dia(data_ref, config.limite_outlier_minutos)
    mensagem = montar_mensagem(config, metricas, agora=agora)

    svc = WhatsAppService()
    ok, resp = svc.enviar_mensagem_texto(destino, mensagem, variar=False)
    if ok:
        logger.info('Relatório de tratamento enviado para %s (data=%s, qtd=%s).',
                    destino, data_ref, metricas['total_geral']['qtd'])
        return True, 'Enviado.'
    logger.warning('Falha ao enviar relatório de tratamento: %s', resp)
    return False, str(resp or 'Falha no envio WhatsApp.')


def _slot_configurado(config: RelatorioTratamentoConfig) -> str | None:
    if not config.horario_envio:
        return None
    return f'{config.horario_envio.hour:02d}:{config.horario_envio.minute:02d}'


def _slot_ja_enviado(config: RelatorioTratamentoConfig, hoje_str: str, slot: str) -> bool:
    controle = config.controle_disparos or {}
    return controle.get('date') == hoje_str and slot in (controle.get('slots') or [])


def _marcar_slot(config: RelatorioTratamentoConfig, hoje_str: str, slot: str) -> None:
    controle = dict(config.controle_disparos or {})
    if controle.get('date') != hoje_str:
        controle = {'date': hoje_str, 'slots': []}
    slots = list(controle.get('slots') or [])
    if slot not in slots:
        slots.append(slot)
    controle['date'] = hoje_str
    controle['slots'] = slots
    config.controle_disparos = controle
    config.save(update_fields=['controle_disparos'])


def processar_envio_relatorio() -> None:
    """Verifica o horário e dispara o relatório (chamado pelo scheduler a cada minuto)."""
    agora = timezone.localtime(timezone.now())
    if agora.weekday() > 4:  # seg-sex
        return

    config = get_config()
    if not config.ativo:
        return

    slot = _slot_configurado(config)
    if not slot:
        return

    hoje_str = agora.strftime('%Y-%m-%d')
    if _slot_ja_enviado(config, hoje_str, slot):
        return

    alvo_min = config.horario_envio.hour * 60 + config.horario_envio.minute
    agora_min = agora.hour * 60 + agora.minute
    atraso = agora_min - alvo_min
    if not (0 <= atraso <= JANELA_ATRASO_MINUTOS):
        return

    ok, _ = enviar_relatorio(config, agora=agora)
    if ok:
        _marcar_slot(config, hoje_str, slot)
