"""Reagendar com o cliente: template WhatsApp disparado em lote pela esteira e fluxo de resposta.

Fluxo: template (Sim, pode reagendar | Não quero mais | Falar com atendente)
→ Sim: 3 opções de data → turno (Manhã/Tarde) → preferência gravada na venda.
Na WhatsAtende o clique em botão chega só como texto; por isso a resposta é casada
pelo texto + sessão ativa do telefone (os ids rc_* valem quando o provedor os repassa).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

from crm_app.esteira_posso_antecipar_service import (
    _chaves_telefone_busca,
    _normalizar_telefone_chave,
)
from crm_app.services.whatsapp.nio_templates import normalizar_texto_botao

logger = logging.getLogger(__name__)

HORAS_LIMITE_SESSAO = 72
PREFIXO_BOTAO = 'rc_'
LIMITE_LOTE = 1000
PAUSA_ENTRE_ENVIOS_S = 0.4

RESPOSTAS_SIM = frozenset({
    'SIM, PODE REAGENDAR', 'SIM PODE REAGENDAR', 'PODE REAGENDAR', 'SIM', 'S', 'PODE', 'REAGENDAR',
})
RESPOSTAS_NAO = frozenset({'NAO QUERO MAIS', 'NAO QUERO', 'NAO', 'N'})
RESPOSTAS_ATENDENTE = frozenset({'FALAR COM ATENDENTE', 'ATENDENTE', 'FALAR COM UM ATENDENTE'})
RESPOSTAS_CURTAS = frozenset({'SIM', 'S', 'NAO', 'N'})

DIAS_SEMANA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
JANELA_TURNO = {'MANHA': 'Manhã (08h às 12h)', 'TARDE': 'Tarde (13h às 18h)'}


def nome_parceiro() -> str:
    return (
        (getattr(settings, 'SITE_BRAND_NAME', '') or '').strip()
        or (getattr(settings, 'SITE_BRAND', '') or '').strip()
        or 'parceiro Nio'
    )


def _normalizar(texto: str) -> str:
    n = normalizar_texto_botao(texto)
    return re.sub(r'[.!]+$', '', n).strip()


def classificar_resposta_inicial(texto: str) -> Optional[str]:
    n = _normalizar(texto)
    if not n:
        return None
    if n in RESPOSTAS_SIM:
        return 'sim'
    if n in RESPOSTAS_NAO:
        return 'nao'
    if n in RESPOSTAS_ATENDENTE:
        return 'atendente'
    return None


def rotulo_data(d: date) -> str:
    return f'{DIAS_SEMANA[d.weekday()]} {d.strftime("%d/%m")}'


def gerar_datas_opcao(*, a_partir_de: Optional[date] = None, quantidade: int = 3) -> list[date]:
    """Próximos dias a partir de amanhã, sem domingo."""
    d = a_partir_de or (timezone.localdate() + timedelta(days=1))
    datas: list[date] = []
    while len(datas) < quantidade:
        if d.weekday() != 6:
            datas.append(d)
        d += timedelta(days=1)
    return datas


def _datas_da_sessao(sessao) -> list[date]:
    try:
        return [date.fromisoformat(s) for s in json.loads(sessao.datas_opcoes_json or '[]')]
    except (TypeError, ValueError):
        return []


def parse_data_resposta(texto: str, opcoes: list[date]) -> Optional[date]:
    n = _normalizar(texto)
    if not n or not opcoes:
        return None
    if n.isdigit() and 1 <= int(n) <= len(opcoes):
        return opcoes[int(n) - 1]
    for d in opcoes:
        if n == _normalizar(rotulo_data(d)):
            return d
    m = re.search(r'(\d{1,2})/(\d{1,2})', n)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        for d in opcoes:
            if d.day == dia and d.month == mes:
                return d
    return None


def parse_turno_resposta(texto: str) -> Optional[str]:
    n = _normalizar(texto)
    if n in ('MANHA', '1', 'DE MANHA', 'PELA MANHA'):
        return 'MANHA'
    if n in ('TARDE', '2', 'A TARDE', 'PELA TARDE', 'DE TARDE'):
        return 'TARDE'
    return None


def parse_button_id(button_id: str) -> Optional[dict]:
    """rc_{venda}_sim|nao|atd|manha|tarde|dt_YYYYMMDD"""
    bid = (button_id or '').strip()
    m = re.match(rf'^{PREFIXO_BOTAO}(\d+)_(sim|nao|atd|manha|tarde)$', bid, re.IGNORECASE)
    if m:
        venda_id = int(m.group(1))
        tipo = m.group(2).lower()
        if tipo in ('manha', 'tarde'):
            return {'venda_id': venda_id, 'acao': 'turno', 'turno': tipo.upper()}
        return {'venda_id': venda_id, 'acao': {'sim': 'sim', 'nao': 'nao', 'atd': 'atendente'}[tipo]}
    m = re.match(rf'^{PREFIXO_BOTAO}(\d+)_dt_(\d{{8}})$', bid, re.IGNORECASE)
    if m:
        ds = m.group(2)
        try:
            d = date(int(ds[0:4]), int(ds[4:6]), int(ds[6:8]))
        except ValueError:
            return None
        return {'venda_id': int(m.group(1)), 'acao': 'data', 'data': d}
    return None


def montar_botoes_datas(venda_id: int, datas: list[date]) -> list:
    return [
        {'id': f'{PREFIXO_BOTAO}{int(venda_id)}_dt_{d.strftime("%Y%m%d")}', 'type': 'REPLY', 'label': rotulo_data(d)}
        for d in datas[:3]
    ]


def montar_botoes_turno(venda_id: int) -> list:
    vid = int(venda_id)
    return [
        {'id': f'{PREFIXO_BOTAO}{vid}_manha', 'type': 'REPLY', 'label': 'Manhã'},
        {'id': f'{PREFIXO_BOTAO}{vid}_tarde', 'type': 'REPLY', 'label': 'Tarde'},
    ]


def montar_texto_fallback(venda) -> str:
    from crm_app.services.whatsapp.nio_templates import primeiro_nome, saudacao_meta

    nome = venda.cliente.nome_razao_social if getattr(venda, 'cliente', None) else ''
    return (
        f'Olá, {saudacao_meta()}! {primeiro_nome(nome)}, aqui é da {nome_parceiro()}, '
        'parceiro oficial da Nio Fibra.\n\n'
        'O agendamento da instalação do seu pedido ficou pendente e queremos remarcar '
        'a visita técnica com você. Podemos reagendar a sua instalação?\n\n'
        'Responda: *SIM*, *NÃO* (não quero mais) ou *ATENDENTE*.'
    )


def _extrair_message_id(resp) -> str:
    if not isinstance(resp, dict):
        return ''
    msgs = resp.get('messages')
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict) and msgs[0].get('id'):
        return str(msgs[0]['id']).strip()
    for key in ('messageId', 'zaapId', 'id', 'message_id'):
        val = resp.get(key)
        if val and isinstance(val, (str, int)):
            return str(val).strip()
    data = resp.get('data')
    return _extrair_message_id(data) if isinstance(data, dict) else ''


# ---------------------------------------------------------------- sessão

def _sessao_ativa_qs(telefone: str = ''):
    from crm_app.models import ReagendamentoClienteSessao as S

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_SESSAO)
    qs = S.objects.filter(
        finalizado_em__isnull=True,
        criado_em__gte=limite,
        etapa__in=(S.ETAPA_SIM_NAO, S.ETAPA_DATA, S.ETAPA_TURNO),
    )
    if telefone:
        chaves = _chaves_telefone_busca(telefone)
        if not chaves:
            return qs.none()
        qs = qs.filter(telefone__in=chaves)
    return qs.select_related('venda', 'venda__cliente')


def localizar_sessao(telefone: str, *, button_id: str = '', reference_message_id: str = ''):
    if not telefone:
        return None
    qs = _sessao_ativa_qs(telefone)
    parsed = parse_button_id(button_id) if button_id else None
    if parsed:
        s = qs.filter(venda_id=parsed['venda_id']).order_by('-criado_em').first()
        if s:
            return s
    ref = (reference_message_id or '').strip()
    if ref:
        s = qs.filter(whatsapp_message_id=ref).order_by('-criado_em').first()
        if s:
            return s
    return qs.order_by('-atualizado_em', '-criado_em').first()


def _interpretar(sessao, texto: str, button_id: str) -> Optional[dict]:
    from crm_app.models import ReagendamentoClienteSessao as S

    parsed = parse_button_id(button_id) if button_id else None
    if parsed:
        return parsed
    if sessao.etapa == S.ETAPA_SIM_NAO:
        acao = classificar_resposta_inicial(texto)
        return {'acao': acao} if acao else None
    if sessao.etapa == S.ETAPA_DATA:
        d = parse_data_resposta(texto, _datas_da_sessao(sessao))
        return {'acao': 'data', 'data': d} if d else None
    if sessao.etapa == S.ETAPA_TURNO:
        t = parse_turno_resposta(texto)
        return {'acao': 'turno', 'turno': t} if t else None
    return None


def deve_tentar_reagendar_cliente(
    mensagem_texto: str,
    *,
    button_id: str = '',
    reference_message_id: str = '',
    telefone: str = '',
) -> bool:
    if (button_id or '').lower().startswith(PREFIXO_BOTAO):
        return True
    sessao = localizar_sessao(telefone, button_id=button_id, reference_message_id=reference_message_id)
    if not sessao:
        return False
    from crm_app.models import ReagendamentoClienteSessao as S

    if sessao.etapa in (S.ETAPA_DATA, S.ETAPA_TURNO) and (mensagem_texto or '').strip():
        return True
    if _interpretar(sessao, mensagem_texto, button_id) is None:
        return False
    if sessao.etapa == S.ETAPA_SIM_NAO and _normalizar(mensagem_texto) in RESPOSTAS_CURTAS:
        return not _lembrete_mais_recente_pendente(sessao, telefone)
    return True


def _lembrete_mais_recente_pendente(sessao, telefone: str) -> bool:
    """SIM/NÃO soltos pertencem ao lembrete de instalação se ele foi enviado depois desta consulta."""
    from crm_app.models import LembreteInstalacaoEnviado

    return LembreteInstalacaoEnviado.objects.filter(
        telefone__in=_chaves_telefone_busca(telefone),
        respondido_em__isnull=True,
        data_envio__gt=sessao.criado_em,
    ).exists()


# ---------------------------------------------------------------- envio de mensagens

def _svc():
    from crm_app.whatsapp_service import WhatsAppService

    return WhatsAppService.para_cliente()


def _enviar_texto(telefone: str, mensagem: str) -> bool:
    ok, _ = _svc().enviar_mensagem_texto(telefone, mensagem, variar=False)
    return bool(ok)


def _enviar_botoes(telefone: str, mensagem: str, botoes: list, texto_alternativo: str) -> tuple[bool, str]:
    try:
        ok, resp = _svc().enviar_mensagem_com_botoes_reply(telefone, mensagem, botoes)
    except Exception:
        logger.exception('[ReagendarCliente] Erro ao enviar botões tel=%s', telefone)
        ok, resp = False, None
    if ok:
        return True, _extrair_message_id(resp)
    return _enviar_texto(telefone, texto_alternativo), ''


def _atualizar_venda(venda, **campos):
    for k, v in campos.items():
        setattr(venda, k, v)
    venda.save(update_fields=list(campos.keys()))


def _pedir_data(sessao, telefone: str):
    from crm_app.models import ReagendamentoClienteSessao as S

    datas = gerar_datas_opcao()
    msg = 'Ótimo! Qual dia fica melhor para a visita técnica?'
    alternativo = msg + '\n\n' + '\n'.join(
        f'*{i}* - {rotulo_data(d)}' for i, d in enumerate(datas, start=1)
    ) + '\n\nResponda com o número da opção.'
    ok, msg_id = _enviar_botoes(telefone, msg, montar_botoes_datas(sessao.venda_id, datas), alternativo)
    sessao.datas_opcoes_json = json.dumps([d.isoformat() for d in datas])
    sessao.etapa = S.ETAPA_DATA
    campos = ['datas_opcoes_json', 'etapa', 'atualizado_em']
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        campos.append('whatsapp_message_id')
    sessao.save(update_fields=campos)
    return ok


def _pedir_turno(sessao, telefone: str, data_escolhida: date):
    from crm_app.models import ReagendamentoClienteSessao as S

    msg = f'Para *{rotulo_data(data_escolhida)}*, qual turno você prefere?'
    alternativo = msg + '\n\n*1* - Manhã (08h às 12h)\n*2* - Tarde (13h às 18h)'
    ok, msg_id = _enviar_botoes(telefone, msg, montar_botoes_turno(sessao.venda_id), alternativo)
    sessao.data_escolhida = data_escolhida
    sessao.etapa = S.ETAPA_TURNO
    campos = ['data_escolhida', 'etapa', 'atualizado_em']
    if msg_id:
        sessao.whatsapp_message_id = msg_id
        campos.append('whatsapp_message_id')
    sessao.save(update_fields=campos)
    return ok


def _finalizar(sessao, etapa: str, **campos_extra):
    agora = timezone.now()
    sessao.etapa = etapa
    sessao.finalizado_em = agora
    sessao.respondido_em = sessao.respondido_em or agora
    for k, v in campos_extra.items():
        setattr(sessao, k, v)
    sessao.save(update_fields=['etapa', 'finalizado_em', 'respondido_em', 'atualizado_em', *campos_extra.keys()])


def processar_resposta_reagendar_cliente(
    telefone_remetente: str,
    mensagem_texto: str,
    *,
    button_id: str = '',
    reference_message_id: str = '',
) -> bool:
    from crm_app.models import ReagendamentoClienteSessao as S, Venda

    sessao = localizar_sessao(
        telefone_remetente, button_id=button_id, reference_message_id=reference_message_id,
    )
    if not sessao:
        if (button_id or '').lower().startswith(PREFIXO_BOTAO):
            _enviar_texto(
                telefone_remetente,
                'Esta consulta de reagendamento expirou ou já foi respondida. '
                'Se precisar, responda *ATENDENTE* que um especialista fala com você.',
            )
            return True
        return False

    acao = _interpretar(sessao, mensagem_texto, button_id)
    venda = sessao.venda
    agora = timezone.now()
    logger.info(
        '[ReagendarCliente] venda #%s etapa=%s acao=%r texto=%r btn=%r',
        venda.id, sessao.etapa, acao, (mensagem_texto or '')[:60], button_id or '-',
    )

    if not acao:
        if sessao.etapa == S.ETAPA_DATA:
            datas = _datas_da_sessao(sessao)
            _enviar_texto(
                telefone_remetente,
                'Escolha uma das datas: '
                + ' | '.join(f'*{i}* - {rotulo_data(d)}' for i, d in enumerate(datas, start=1))
                + '\n\nOu responda *ATENDENTE* para falar com um especialista.',
            )
            return True
        if sessao.etapa == S.ETAPA_TURNO:
            _enviar_texto(telefone_remetente, 'Escolha o turno: *1* - Manhã ou *2* - Tarde.')
            return True
        return False

    tipo = acao.get('acao')
    if tipo == 'atendente':
        _finalizar(sessao, S.ETAPA_ATENDENTE)
        _atualizar_venda(
            venda,
            cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_ATENDENTE,
            cliente_reagendar_respondido_em=agora,
        )
        _enviar_texto(telefone_remetente, 'Em breve um especialista irá falar contigo.')
        return True

    if tipo == 'nao':
        _finalizar(sessao, S.ETAPA_RECUSADO)
        _atualizar_venda(
            venda,
            cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_NAO,
            cliente_reagendar_respondido_em=agora,
        )
        _enviar_texto(
            telefone_remetente,
            'Tudo bem, registramos que você não deseja mais seguir com a instalação. Obrigado pelo retorno!',
        )
        return True

    if tipo == 'sim':
        if sessao.etapa != S.ETAPA_SIM_NAO:
            return True
        sessao.respondido_em = agora
        sessao.save(update_fields=['respondido_em', 'atualizado_em'])
        _atualizar_venda(
            venda,
            cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_SIM,
            cliente_reagendar_respondido_em=agora,
        )
        _pedir_data(sessao, telefone_remetente)
        return True

    if tipo == 'data':
        if sessao.etapa not in (S.ETAPA_DATA, S.ETAPA_TURNO):
            return True
        _pedir_turno(sessao, telefone_remetente, acao['data'])
        return True

    if tipo == 'turno':
        if sessao.etapa != S.ETAPA_TURNO or not sessao.data_escolhida:
            return True
        turno = acao['turno']
        _finalizar(sessao, S.ETAPA_CONCLUIDO, periodo_escolhido=turno)
        _atualizar_venda(
            venda,
            cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_DEFINIDO,
            cliente_reagendar_data=sessao.data_escolhida,
            cliente_reagendar_turno=turno,
            cliente_reagendar_respondido_em=agora,
        )
        _enviar_texto(
            telefone_remetente,
            f'Perfeito! Registramos sua preferência: *{rotulo_data(sessao.data_escolhida)}*, '
            f'{JANELA_TURNO.get(turno, turno)}.\n\n'
            'Vamos solicitar o reagendamento e você receberá a confirmação da Nio. Obrigado!',
        )
        return True

    return False


# ---------------------------------------------------------------- disparo

def enviar_reagendar_cliente(venda, *, usuario=None) -> dict:
    """Envia o template ao telefone1 da venda e abre a sessão de resposta."""
    from crm_app.models import ReagendamentoClienteSessao as S, Venda
    from crm_app.services.whatsapp.nio_templates import (
        TEMPLATE_REAGENDAMENTO_CLIENTE,
        body_params_reagendamento_cliente,
        tentar_enviar_ou_texto,
    )

    resultado = {'ok': False, 'detail': ''}
    agora = timezone.now()
    telefone = (getattr(venda, 'telefone1', None) or '').strip()
    tel_chave = _normalizar_telefone_chave(telefone)
    if len(tel_chave) < 10:
        _atualizar_venda(
            venda,
            cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_FALHA_ENVIO,
            cliente_reagendar_enviado_em=agora,
        )
        resultado['detail'] = 'Venda sem telefone válido.'
        return resultado

    nome = venda.cliente.nome_razao_social if getattr(venda, 'cliente', None) else ''
    try:
        ok, resp, canal = tentar_enviar_ou_texto(
            telefone,
            TEMPLATE_REAGENDAMENTO_CLIENTE,
            body_params_reagendamento_cliente(nome, nome_parceiro()),
            montar_texto_fallback(venda),
        )
    except Exception as exc:
        logger.exception('[ReagendarCliente] Erro ao enviar venda #%s', venda.id)
        ok, resp, canal = False, str(exc), ''

    if not ok:
        _atualizar_venda(
            venda,
            cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_FALHA_ENVIO,
            cliente_reagendar_enviado_em=agora,
        )
        resultado['detail'] = 'Falha ao enviar (API WhatsApp).'
        return resultado

    S.objects.filter(venda=venda, finalizado_em__isnull=True).update(finalizado_em=agora)
    S.objects.create(
        telefone=tel_chave,
        venda=venda,
        enviado_por=usuario,
        etapa=S.ETAPA_SIM_NAO,
        whatsapp_message_id=_extrair_message_id(resp),
        canal=canal or '',
    )
    _atualizar_venda(
        venda,
        cliente_reagendar_status=Venda.REAGENDAR_CLIENTE_ENVIADO,
        cliente_reagendar_enviado_em=agora,
        cliente_reagendar_respondido_em=None,
        cliente_reagendar_data=None,
        cliente_reagendar_turno='',
    )
    resultado.update(ok=True, detail=f'Enviado ({canal}).')
    return resultado


def resumo_lote(qs) -> dict:
    """Contagem para a confirmação: quem recebe e quem fica de fora."""
    from crm_app.models import Venda

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_SESSAO)
    total = qs.count()
    aguardando_qs = qs.filter(
        cliente_reagendar_status__in=(Venda.REAGENDAR_CLIENTE_ENVIADO, Venda.REAGENDAR_CLIENTE_SIM),
        cliente_reagendar_enviado_em__gte=limite,
    )
    sem_telefone = qs.filter(telefone1__isnull=True).count() + qs.filter(telefone1='').count()
    aguardando = aguardando_qs.count()
    elegiveis = (
        qs.exclude(id__in=aguardando_qs.values('id'))
        .exclude(telefone1__isnull=True)
        .exclude(telefone1='')
    )
    return {
        'total': total,
        'sem_telefone': sem_telefone,
        'aguardando_resposta': aguardando,
        'a_enviar': elegiveis.count(),
        'elegiveis_qs': elegiveis,
    }


def disparar_lote_em_background(venda_ids: list[int], usuario_id: Optional[int]) -> None:
    import threading

    def _runner():
        import django.db
        from django.contrib.auth import get_user_model

        from crm_app.models import Venda

        django.db.close_old_connections()
        enviados = falhas = 0
        try:
            usuario = get_user_model().objects.filter(id=usuario_id).first() if usuario_id else None
            for vid in venda_ids:
                venda = Venda.objects.select_related('cliente').filter(id=vid).first()
                if not venda:
                    continue
                r = enviar_reagendar_cliente(venda, usuario=usuario)
                if r.get('ok'):
                    enviados += 1
                else:
                    falhas += 1
                time.sleep(PAUSA_ENTRE_ENVIOS_S)
        except Exception:
            logger.exception('[ReagendarCliente] Erro no lote')
        finally:
            logger.info(
                '[ReagendarCliente] Lote concluído: %s enviados, %s falhas (de %s)',
                enviados, falhas, len(venda_ids),
            )
            django.db.close_old_connections()

    threading.Thread(target=_runner, name='reagendar-cliente-lote', daemon=True).start()
