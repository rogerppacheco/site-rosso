"""Consulta 'Posso agendar novamente?' ao consultor (vendedor) na esteira — fluxo WhatsApp em etapas."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Optional

from django.utils import timezone

from crm_app.esteira_pendencia_cliente_service import venda_em_status_pendente
from crm_app.esteira_posso_antecipar_service import (
    _chaves_telefone_busca,
    _extrair_message_id_resposta_zapi,
    _extrair_reference_message_id_zapi,
    _normalizar_telefone_chave,
    telefone_vendedor_para_envio_sistema,
)

logger = logging.getLogger(__name__)

HORAS_LIMITE_SESSAO = 72
PREFIXO_BOTAO = 'pr_'


def _texto_pendencia(venda) -> str:
    motivo = getattr(venda, 'motivo_pendencia', None)
    if not motivo:
        return '—'
    nome = (getattr(motivo, 'nome', None) or '').strip()
    tipo = (getattr(motivo, 'tipo_pendencia', None) or '').strip()
    if nome and tipo:
        return f'{nome} ({tipo})'
    return nome or tipo or '—'


def _formatar_data_botao(d: date) -> str:
    dias = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
    wd = dias[d.weekday()]
    return f'{wd} {d.strftime("%d/%m")}'


def gerar_tres_datas_opcao(*, a_partir_de: Optional[date] = None) -> list[date]:
    """Próximos 3 dias corridos a partir de amanhã (ou a_partir_de)."""
    base = a_partir_de or (timezone.localdate() + timedelta(days=1))
    return [base + timedelta(days=i) for i in range(3)]


def montar_mensagem_inicial_posso_reagendar(venda) -> str:
    nome_cliente = ''
    if getattr(venda, 'cliente', None):
        nome_cliente = (venda.cliente.nome_razao_social or '').strip()
    os_txt = (getattr(venda, 'ordem_servico', None) or '').strip() or '—'
    pend = _texto_pendencia(venda)
    header = f'Olá! Sobre o pedido *#{venda.id}*'
    if nome_cliente:
        header += f' — cliente *{nome_cliente}*'
    header += f' (O.S. *{os_txt}*):'
    return '\n'.join([
        header,
        '',
        f'Este pedido está na pendência *{pend}*.',
        '',
        'Posso tentar *agendar novamente*?',
        '',
        'Toque em *Sim* ou *Não* abaixo.',
    ])


def montar_botoes_sim_nao(venda_id: int) -> list:
    vid = int(venda_id)
    return [
        {'id': f'{PREFIXO_BOTAO}{vid}_sim', 'type': 'REPLY', 'label': 'Sim'},
        {'id': f'{PREFIXO_BOTAO}{vid}_nao', 'type': 'REPLY', 'label': 'Não'},
    ]


def montar_botoes_datas(venda_id: int, datas: list[date]) -> list:
    vid = int(venda_id)
    botoes = []
    for d in datas[:3]:
        botoes.append({
            'id': f'{PREFIXO_BOTAO}{vid}_dt_{d.strftime("%Y%m%d")}',
            'type': 'REPLY',
            'label': _formatar_data_botao(d)[:20],
        })
    return botoes


def montar_botoes_turno(venda_id: int) -> list:
    vid = int(venda_id)
    return [
        {'id': f'{PREFIXO_BOTAO}{vid}_manha', 'type': 'REPLY', 'label': 'Manhã'},
        {'id': f'{PREFIXO_BOTAO}{vid}_tarde', 'type': 'REPLY', 'label': 'Tarde'},
    ]


def parse_button_id_posso_reagendar(button_id: str) -> Optional[dict]:
    """
    pr_{venda_id}_sim|nao|dt_YYYYMMDD|manha|tarde
    """
    bid = (button_id or '').strip()
    m = re.match(rf'^{PREFIXO_BOTAO}(\d+)_(sim|nao|manha|tarde)$', bid, re.IGNORECASE)
    if m:
        venda_id = int(m.group(1))
        tipo = m.group(2).lower()
        if tipo == 'sim':
            return {'venda_id': venda_id, 'acao': 'sim', 'pode': True}
        if tipo == 'nao':
            return {'venda_id': venda_id, 'acao': 'nao', 'pode': False}
        if tipo == 'manha':
            return {'venda_id': venda_id, 'acao': 'turno', 'turno': 'MANHA'}
        if tipo == 'tarde':
            return {'venda_id': venda_id, 'acao': 'turno', 'turno': 'TARDE'}
    m_dt = re.match(rf'^{PREFIXO_BOTAO}(\d+)_dt_(\d{{8}})$', bid, re.IGNORECASE)
    if m_dt:
        ds = m_dt.group(2)
        try:
            data_escolhida = date(int(ds[0:4]), int(ds[4:6]), int(ds[6:8]))
        except (TypeError, ValueError):
            return None
        return {'venda_id': int(m_dt.group(1)), 'acao': 'data', 'data': data_escolhida}
    return None


def formatar_reagendar_consultor_exibicao(venda) -> str:
    if getattr(venda, 'consultor_pode_reagendar', None) is True:
        d = getattr(venda, 'consultor_reagendar_data', None)
        t = getattr(venda, 'consultor_reagendar_turno', None)
        if d and t == 'MANHA':
            return f'Sim — {d.strftime("%d/%m")} Manhã'
        if d and t == 'TARDE':
            return f'Sim — {d.strftime("%d/%m")} Tarde'
        if d:
            return f'Sim — {d.strftime("%d/%m")}'
        return 'Sim'
    if getattr(venda, 'consultor_pode_reagendar', None) is False:
        return 'Não'
    if (
        getattr(venda, 'data_solicitacao_reagendar_consultor', None)
        and not getattr(venda, 'data_resposta_reagendar_consultor', None)
    ):
        return 'Aguardando'
    resp = (getattr(venda, 'consultor_reagendar_resposta', None) or '').strip()
    if resp:
        return resp[:80]
    return '-'


def _nome_consultor_venda(venda) -> str:
    vendedor = getattr(venda, 'vendedor', None)
    if vendedor:
        return (getattr(vendedor, 'username', None) or '').strip()
    return (getattr(venda, 'vendedor_nome', None) or '').strip()


def formatar_reagendar_consultor_exibicao_com_consultor(venda) -> str:
    """Resumo para coluna/Excel: consultor + resposta (ex.: FERNANDA: Sim — 01/06 Manhã)."""
    resumo = formatar_reagendar_consultor_exibicao(venda)
    if resumo == '-':
        return resumo
    nome = _nome_consultor_venda(venda)
    if nome:
        return f'{nome}: {resumo}'
    return resumo


def consultor_respondeu_reagendar(venda) -> str:
    """Username do consultor quando já houve resposta ao fluxo."""
    if not getattr(venda, 'data_resposta_reagendar_consultor', None):
        return ''
    return _nome_consultor_venda(venda)


def _sessao_ativa_qs(telefone: str = ''):
    from crm_app.models import PossoReagendarConsultorSessao

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_SESSAO)
    qs = PossoReagendarConsultorSessao.objects.filter(
        finalizado_em__isnull=True,
        criado_em__gte=limite,
    ).exclude(etapa__in=(
        PossoReagendarConsultorSessao.ETAPA_CONCLUIDO,
        PossoReagendarConsultorSessao.ETAPA_RECUSADO,
    ))
    if telefone:
        chaves = _chaves_telefone_busca(telefone)
        if chaves:
            qs = qs.filter(telefone__in=chaves)
    return qs.select_related('venda', 'venda__vendedor', 'venda__motivo_pendencia')


def buscar_sessao_por_mensagem_whatsapp(reference_message_id: str, telefone: str = ''):
    from crm_app.models import PossoReagendarConsultorSessao

    ref = (reference_message_id or '').strip()
    if not ref:
        return None
    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_SESSAO)
    qs = PossoReagendarConsultorSessao.objects.filter(
        whatsapp_message_id=ref,
        criado_em__gte=limite,
        finalizado_em__isnull=True,
    ).select_related('venda', 'venda__vendedor')
    if telefone:
        chaves = _chaves_telefone_busca(telefone)
        if chaves:
            qs = qs.filter(telefone__in=chaves)
    return qs.order_by('-criado_em').first()


def buscar_sessao_ativa_por_venda(venda_id: int, telefone: str):
    if not venda_id:
        return None
    return (
        _sessao_ativa_qs(telefone)
        .filter(venda_id=int(venda_id))
        .order_by('-criado_em')
        .first()
    )


def _enviar_botoes(telefone: str, mensagem: str, botoes: list, footer: str = '') -> tuple[bool, str]:
    from crm_app.whatsapp_service import WhatsAppService

    svc = WhatsAppService()
    ok, resp = svc.enviar_mensagem_com_botoes_reply(telefone, mensagem, botoes, footer=footer)
    msg_id = _extrair_message_id_resposta_zapi(resp)
    return bool(ok), msg_id


def _enviar_texto(telefone: str, mensagem: str) -> bool:
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.whatsapp_webhook_handler import formatar_telefone

    tel = formatar_telefone(telefone)
    if not tel:
        return False
    ok, _ = WhatsAppService().enviar_mensagem_texto(tel, mensagem, variar=False)
    return bool(ok)


def _finalizar_sessao(sessao, etapa_final: str):
    from crm_app.models import PossoReagendarConsultorSessao

    agora = timezone.now()
    sessao.etapa = etapa_final
    sessao.finalizado_em = agora
    sessao.save(update_fields=['etapa', 'finalizado_em', 'atualizado_em'])
    if etapa_final in (PossoReagendarConsultorSessao.ETAPA_CONCLUIDO, PossoReagendarConsultorSessao.ETAPA_RECUSADO):
        venda = sessao.venda
        venda.data_resposta_reagendar_consultor = agora
        venda.save(update_fields=['data_resposta_reagendar_consultor'])


def _gravar_venda_recusado(sessao, telefone: str):
    from crm_app.models import PossoReagendarConsultorSessao

    venda = sessao.venda
    agora = timezone.now()
    venda.consultor_pode_reagendar = False
    venda.consultor_reagendar_resposta = 'Não'
    venda.data_resposta_reagendar_consultor = agora
    venda.save(update_fields=[
        'consultor_pode_reagendar',
        'consultor_reagendar_resposta',
        'data_resposta_reagendar_consultor',
    ])
    sessao.pode_reagendar = False
    sessao.save(update_fields=['pode_reagendar', 'atualizado_em'])
    _finalizar_sessao(sessao, PossoReagendarConsultorSessao.ETAPA_RECUSADO)
    _enviar_texto(
        telefone,
        f'Resposta registrada para o pedido *#{venda.id}*: *Não* (não reagendar). Obrigado!',
    )


def _gravar_venda_concluido(sessao, telefone: str):
    from crm_app.models import PossoReagendarConsultorSessao

    venda = sessao.venda
    agora = timezone.now()
    turno_txt = 'Manhã' if sessao.periodo_escolhido == 'MANHA' else 'Tarde'
    data_txt = sessao.data_escolhida.strftime('%d/%m/%Y') if sessao.data_escolhida else '—'
    resumo = f'Sim — reagendar em {data_txt} ({turno_txt})'

    venda.consultor_pode_reagendar = True
    venda.consultor_reagendar_data = sessao.data_escolhida
    venda.consultor_reagendar_turno = sessao.periodo_escolhido
    venda.consultor_reagendar_resposta = resumo
    venda.data_resposta_reagendar_consultor = agora
    venda.save(update_fields=[
        'consultor_pode_reagendar',
        'consultor_reagendar_data',
        'consultor_reagendar_turno',
        'consultor_reagendar_resposta',
        'data_resposta_reagendar_consultor',
    ])
    _finalizar_sessao(sessao, PossoReagendarConsultorSessao.ETAPA_CONCLUIDO)
    _enviar_texto(
        telefone,
        f'Resposta registrada para o pedido *#{venda.id}*: *{resumo}*. Obrigado!',
    )


def _etapa_sim_nao(sessao, parsed_btn: dict, telefone: str) -> bool:
    from crm_app.models import PossoReagendarConsultorSessao

    if parsed_btn.get('acao') == 'nao':
        _gravar_venda_recusado(sessao, telefone)
        return True

    if parsed_btn.get('acao') != 'sim':
        return False

    datas = gerar_tres_datas_opcao()
    msg = (
        f'Pedido *#{sessao.venda_id}*: em qual dia podemos tentar o reagendamento?\n\n'
        'Escolha uma das opções:'
    )
    ok, msg_id = _enviar_botoes(
        telefone,
        msg,
        montar_botoes_datas(sessao.venda_id, datas),
        footer=f'Pedido #{sessao.venda_id}',
    )
    if not ok:
        logger.error(
            '[PossoReagendar] Falha ao enviar opções de data venda #%s tel=%s',
            sessao.venda_id,
            telefone,
        )
        _enviar_texto(
            telefone,
            f'Não consegui enviar as opções de data para o pedido *#{sessao.venda_id}*. '
            'Avise o backoffice ou tente novamente.',
        )
        return True

    sessao.pode_reagendar = True
    sessao.datas_opcoes_json = json.dumps([d.isoformat() for d in datas])
    sessao.etapa = PossoReagendarConsultorSessao.ETAPA_DATA
    update_fields = ['pode_reagendar', 'datas_opcoes_json', 'etapa', 'atualizado_em']
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        update_fields.append('whatsapp_message_id')
    sessao.save(update_fields=update_fields)
    logger.info(
        '[PossoReagendar] Sim → datas enviadas venda #%s messageId=%s',
        sessao.venda_id,
        msg_id or '-',
    )
    return True


def _etapa_data(sessao, parsed_btn: dict, telefone: str) -> bool:
    from crm_app.models import PossoReagendarConsultorSessao

    if parsed_btn.get('acao') != 'data':
        return False
    data_esc = parsed_btn.get('data')
    if not data_esc:
        return False

    sessao.data_escolhida = data_esc
    sessao.etapa = PossoReagendarConsultorSessao.ETAPA_TURNO
    sessao.save(update_fields=['data_escolhida', 'etapa', 'atualizado_em'])

    data_fmt = data_esc.strftime('%d/%m/%Y')
    msg = f'Pedido *#{sessao.venda_id}*: para o dia *{data_fmt}*, qual turno?'
    ok, msg_id = _enviar_botoes(
        telefone,
        msg,
        montar_botoes_turno(sessao.venda_id),
        footer=f'Pedido #{sessao.venda_id}',
    )
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        sessao.save(update_fields=['whatsapp_message_id', 'atualizado_em'])
    return bool(ok)


def _etapa_turno(sessao, parsed_btn: dict, telefone: str) -> bool:
    if parsed_btn.get('acao') != 'turno':
        return False
    turno = parsed_btn.get('turno')
    if turno not in ('MANHA', 'TARDE'):
        return False
    sessao.periodo_escolhido = turno
    sessao.save(update_fields=['periodo_escolhido', 'atualizado_em'])
    _gravar_venda_concluido(sessao, telefone)
    return True


def deve_tentar_posso_reagendar(
    mensagem_texto: str,
    *,
    button_id: str = '',
    reference_message_id: str = '',
    telefone: str = '',
) -> bool:
    if button_id and (button_id.startswith(PREFIXO_BOTAO) or parse_button_id_posso_reagendar(button_id)):
        return True
    ref = (reference_message_id or '').strip()
    if ref and telefone and buscar_sessao_por_mensagem_whatsapp(ref, telefone):
        return True
    norm = (mensagem_texto or '').strip().upper()
    if norm in ('SIM', 'NÃO', 'NAO', 'S', 'N') and telefone:
        return _sessao_ativa_qs(telefone).exists()
    return False


def tentar_enviar_posso_reagendar_consultor(venda, *, usuario=None) -> dict:
    from crm_app.models import PossoReagendarConsultorSessao

    resultado = {'ok': True, 'enviado': False, 'detail': '', 'mensagem': ''}

    if not venda_em_status_pendente(venda):
        resultado['ok'] = False
        resultado['detail'] = 'Disponível apenas para vendas com status PENDENTE.'
        return resultado
    if not getattr(venda, 'motivo_pendencia_id', None):
        resultado['ok'] = False
        resultado['detail'] = 'Venda sem motivo de pendência cadastrado.'
        return resultado
    if not getattr(venda, 'vendedor_id', None):
        resultado['ok'] = False
        resultado['detail'] = 'Venda sem consultor/vendedor vinculado.'
        return resultado

    telefone, err_tel = telefone_vendedor_para_envio_sistema(venda)
    if not telefone:
        resultado['ok'] = False
        resultado['detail'] = err_tel or 'Consultor sem WhatsApp cadastrado.'
        return resultado

    mensagem = montar_mensagem_inicial_posso_reagendar(venda)
    resultado['mensagem'] = mensagem

    try:
        ok, msg_id = _enviar_botoes(
            telefone,
            mensagem,
            montar_botoes_sim_nao(venda.id),
            footer=f'Pedido #{venda.id}',
        )
        if not ok:
            resultado['ok'] = False
            resultado['detail'] = 'Falha ao enviar mensagem (API WhatsApp).'
            return resultado

        tel_chave = _normalizar_telefone_chave(telefone)
        agora = timezone.now()

        _sessao_ativa_qs(telefone).filter(venda_id=venda.id).update(
            finalizado_em=agora,
            etapa=PossoReagendarConsultorSessao.ETAPA_RECUSADO,
        )

        PossoReagendarConsultorSessao.objects.create(
            telefone=tel_chave or telefone,
            venda=venda,
            vendedor=venda.vendedor,
            solicitado_por=usuario,
            etapa=PossoReagendarConsultorSessao.ETAPA_SIM_NAO,
            whatsapp_message_id=msg_id or '',
        )
        venda.data_solicitacao_reagendar_consultor = agora
        venda.save(update_fields=['data_solicitacao_reagendar_consultor'])

        vendedor_nome = (
            getattr(getattr(venda, 'vendedor', None), 'username', None) or 'consultor'
        )
        if msg_id:
            logger.info(
                '[PossoReagendar] Enviado venda #%s consultor=%s tel=%s messageId=%s',
                venda.id,
                vendedor_nome,
                tel_chave or telefone,
                msg_id,
            )
        resultado['enviado'] = True
        resultado['detail'] = 'Mensagem enviada ao consultor.'
    except Exception as exc:
        resultado['ok'] = False
        resultado['detail'] = str(exc)
        logger.exception('Erro ao enviar posso reagendar venda #%s', venda.id)

    return resultado


def processar_resposta_posso_reagendar_consultor(
    telefone_remetente,
    mensagem_texto,
    *,
    button_id: str = '',
    reference_message_id: str = '',
) -> bool:
    if not deve_tentar_posso_reagendar(
        mensagem_texto or '',
        button_id=button_id,
        reference_message_id=reference_message_id,
        telefone=telefone_remetente,
    ):
        return False

    parsed_btn = parse_button_id_posso_reagendar(button_id) if button_id else None
    ref = (reference_message_id or '').strip()

    logger.info(
        '[PossoReagendar] Processando tel=%s btn=%r ref=%r msg=%r',
        telefone_remetente,
        button_id or '-',
        ref or '-',
        (mensagem_texto or '')[:80],
    )

    sessao = None
    if ref:
        sessao = buscar_sessao_por_mensagem_whatsapp(ref, telefone_remetente)
    if sessao is None and parsed_btn:
        sessao = buscar_sessao_ativa_por_venda(parsed_btn['venda_id'], telefone_remetente)
    if sessao is None:
        ativas = list(_sessao_ativa_qs(telefone_remetente).order_by('-criado_em')[:1])
        sessao = ativas[0] if len(ativas) == 1 else None

    if not sessao:
        if parsed_btn or ref:
            _enviar_texto(
                telefone_remetente,
                'Não encontrei consulta de reagendamento pendente para esta mensagem. '
                'Pode ter expirado ou já foi respondida.',
            )
            return True
        return False

    from crm_app.models import PossoReagendarConsultorSessao

    if sessao.finalizado_em:
        _enviar_texto(
            telefone_remetente,
            f'O pedido *#{sessao.venda_id}* já foi respondido. Avise o backoffice se precisar alterar.',
        )
        return True

    if not parsed_btn and (mensagem_texto or '').strip():
        norm = (mensagem_texto or '').strip().upper()
        if norm in ('SIM', 'S'):
            parsed_btn = {'venda_id': sessao.venda_id, 'acao': 'sim', 'pode': True}
        elif norm in ('NAO', 'NÃO', 'N'):
            parsed_btn = {'venda_id': sessao.venda_id, 'acao': 'nao', 'pode': False}

    if not parsed_btn:
        _enviar_texto(
            telefone_remetente,
            f'Use os *botões* da mensagem do pedido *#{sessao.venda_id}* para responder.',
        )
        return True

    if parsed_btn.get('venda_id') and parsed_btn['venda_id'] != sessao.venda_id:
        sessao = buscar_sessao_ativa_por_venda(parsed_btn['venda_id'], telefone_remetente) or sessao

    etapa = sessao.etapa
    if etapa == PossoReagendarConsultorSessao.ETAPA_SIM_NAO:
        return _etapa_sim_nao(sessao, parsed_btn, telefone_remetente)
    if etapa == PossoReagendarConsultorSessao.ETAPA_DATA:
        return _etapa_data(sessao, parsed_btn, telefone_remetente)
    if etapa == PossoReagendarConsultorSessao.ETAPA_TURNO:
        return _etapa_turno(sessao, parsed_btn, telefone_remetente)

    return False
