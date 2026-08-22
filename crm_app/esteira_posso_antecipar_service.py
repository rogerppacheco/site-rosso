"""Consulta 'Posso antecipar?' ao vendedor na esteira de vendas (WhatsApp + parse da resposta)."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

HORAS_LIMITE_RESPOSTA = 72


def _extrair_message_id_resposta_zapi(resp) -> str:
    if not resp or not isinstance(resp, dict):
        return ''
    for key in ('messageId', 'zaapId', 'id', 'message_id'):
        val = resp.get(key)
        if val:
            return str(val).strip()
    return ''


def _extrair_reference_message_id_zapi(data) -> str:
    if not isinstance(data, dict):
        return ''
    for key in ('referenceMessageId', 'quotedMessageId', 'quotedMsgId', 'referenceMsgId'):
        val = data.get(key)
        if val:
            return str(val).strip()
    for nested in ('message', 'data', 'payload'):
        sub = data.get(nested)
        if isinstance(sub, dict):
            ref = _extrair_reference_message_id_zapi(sub)
            if ref:
                return ref
    return ''


def _normalizar_texto_resposta(texto: str) -> str:
    nfd = unicodedata.normalize('NFD', (texto or '').strip())
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn').upper()


def _normalizar_telefone_chave(telefone: str) -> str:
    if not telefone:
        return ''
    tel = re.sub(r'\D', '', str(telefone))
    if tel.startswith('55') and len(tel) > 12:
        tel = tel[2:]
    return tel


def _extrair_venda_id_da_mensagem(mensagem: str) -> Optional[int]:
    if not mensagem:
        return None
    m = re.search(r'(?:#|protocolo\s*:?\s*)(\d+)', mensagem, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def parse_resposta_posso_antecipar_vendedor(mensagem: str) -> dict:
    """
    Interpreta resposta do vendedor.
    Padrão esperado: Sim, manhã | Sim, tarde | Não
    Retorna: pode (True/False/None), turno (MANHA/TARDE/None), resposta_completa, observacao.
    """
    original = (mensagem or '').strip()
    norm = _normalizar_texto_resposta(original)

    pode = None
    turno = None

    # Rótulos exatos dos botões (prioridade)
    if re.match(r'^\s*SIM\b', norm) and re.search(r'\bMANHA\b', norm):
        return {
            'pode': True,
            'turno': 'MANHA',
            'resposta_completa': original or 'Sim, manhã',
            'observacao': '',
        }
    if re.match(r'^\s*SIM\b', norm) and re.search(r'\bTARDE\b', norm):
        return {
            'pode': True,
            'turno': 'TARDE',
            'resposta_completa': original or 'Sim, tarde',
            'observacao': '',
        }
    if re.match(r'^\s*NAO\b', norm) and len(original) <= 8:
        return {
            'pode': False,
            'turno': None,
            'resposta_completa': original or 'Não',
            'observacao': '',
        }

    # Texto longo com "nao"/"sim" no meio = observação, não Sim/Não estruturado
    if len(original) > 30 and not re.match(r'^\s*(SIM|NAO)\b', norm):
        obs = original
        return {
            'pode': None,
            'turno': None,
            'resposta_completa': original,
            'observacao': obs[:2000] if obs else '',
        }

    tem_nao = bool(re.search(r'(?:^|\b)NAO(?:\b|,|\s|$)', norm))
    tem_sim = bool(re.search(r'(?:^|\b)SIM(?:\b|,|\s|$)', norm))

    if re.match(r'^\s*NAO\b', norm):
        pode = False
    elif re.match(r'^\s*SIM\b', norm):
        pode = True
    elif tem_nao and not tem_sim:
        pode = False
    elif tem_sim and not tem_nao:
        pode = True

    if re.search(r'\bMANHA\b', norm):
        turno = 'MANHA'
    elif re.search(r'\bTARDE\b', norm):
        turno = 'TARDE'

    obs = original
    for pat in (
        r'(?i)\bsim\b',
        r'(?i)\bnao\b',
        r'(?i)\bnão\b',
        r'(?i)\bmanha\b',
        r'(?i)\bmanhã\b',
        r'(?i)\btarde\b',
        r'[,;:\-\.]+',
        r'(?i)\bprotocolo\b',
        r'#\d+',
    ):
        obs = re.sub(pat, ' ', obs)
    obs = re.sub(r'\s+', ' ', obs).strip()
    if not obs or obs.lower() in ('s', 'n'):
        obs = ''

    return {
        'pode': pode,
        'turno': turno,
        'resposta_completa': original,
        'observacao': obs[:2000] if obs else '',
    }


def parse_button_id_posso_antecipar(button_id: str) -> Optional[dict]:
    """
    Botões Z-API: pa_{venda_id}_sim_manha | pa_{venda_id}_sim_tarde | pa_{venda_id}_nao
    """
    m = re.match(r'^pa_(\d+)_(sim_manha|sim_tarde|nao)$', (button_id or '').strip(), re.IGNORECASE)
    if not m:
        return None
    venda_id = int(m.group(1))
    tipo = m.group(2).lower()
    if tipo == 'sim_manha':
        return {
            'venda_id': venda_id,
            'pode': True,
            'turno': 'MANHA',
            'resposta_completa': 'Sim, manhã',
            'observacao': '',
        }
    if tipo == 'sim_tarde':
        return {
            'venda_id': venda_id,
            'pode': True,
            'turno': 'TARDE',
            'resposta_completa': 'Sim, tarde',
            'observacao': '',
        }
    return {
        'venda_id': venda_id,
        'pode': False,
        'turno': None,
        'resposta_completa': 'Não',
        'observacao': '',
    }


def montar_botoes_posso_antecipar(venda_id: int) -> list:
    """Três botões REPLY (máx. WhatsApp) com id único por pedido."""
    vid = int(venda_id)
    return [
        {'id': f'pa_{vid}_sim_manha', 'type': 'REPLY', 'label': 'Sim, manhã'},
        {'id': f'pa_{vid}_sim_tarde', 'type': 'REPLY', 'label': 'Sim, tarde'},
        {'id': f'pa_{vid}_nao', 'type': 'REPLY', 'label': 'Não'},
    ]


def montar_mensagem_posso_antecipar(venda) -> str:
    nome_cliente = ''
    if getattr(venda, 'cliente', None):
        nome_cliente = (venda.cliente.nome_razao_social or '').strip()
    os_txt = (getattr(venda, 'ordem_servico', None) or '').strip() or '—'
    header = f'Olá! Sobre o pedido *#{venda.id}*'
    if nome_cliente:
        header += f' — cliente *{nome_cliente}*'
    header += f' (O.S. *{os_txt}*):'

    return '\n'.join([
        header,
        '',
        'Posso tentar antecipar este pedido?',
        '',
        'É uma *tentativa* — *não prometer* para o cliente, só verificar se ele pode atender *hoje ou amanhã*.',
        '',
        'Toque em um dos botões abaixo para responder *este pedido* (#{vid}).'.format(vid=venda.id),
    ])


def _digitos_telefone_br(telefone: str) -> str:
    dig = re.sub(r'\D', '', str(telefone or ''))
    if dig.startswith('55') and len(dig) > 11:
        dig = dig[2:]
    return dig


def _telefones_cliente_venda(venda) -> set[str]:
    chaves = set()
    for campo in ('telefone1', 'telefone2'):
        dig = _digitos_telefone_br(getattr(venda, campo, None) or '')
        if dig:
            chaves.add(dig)
            if len(dig) >= 10:
                chaves.add(dig[-10:])
    return chaves


def telefone_vendedor_para_envio_sistema(venda) -> tuple[Optional[str], str]:
    """
    WhatsApp do vendedor/consultor para envios do sistema (esteira).
    Usa apenas WhatsApp 1 (tel_whatsapp) — nunca telefone1/telefone2 da venda (cliente).
    """
    vendedor = getattr(venda, 'vendedor', None)
    if not vendedor:
        return None, 'Venda sem consultor/vendedor vinculado.'
    tel = (getattr(vendedor, 'tel_whatsapp', None) or '').strip()
    if not tel:
        return None, 'Consultor sem WhatsApp principal (WhatsApp 1) cadastrado.'
    dig_v = _digitos_telefone_br(tel)
    if not dig_v:
        return None, 'WhatsApp do consultor inválido no cadastro.'
    clientes = _telefones_cliente_venda(venda)
    if dig_v in clientes or (len(dig_v) >= 10 and dig_v[-10:] in clientes):
        nome = (getattr(vendedor, 'username', None) or 'consultor').strip()
        return None, (
            f'O WhatsApp 1 de {nome} coincide com o telefone do cliente nesta venda. '
            'Corrija o cadastro do consultor antes de enviar.'
        )
    return tel, ''


def _telefone_vendedor(venda) -> Optional[str]:
    tel, _ = telefone_vendedor_para_envio_sistema(venda)
    return tel


def _mensagem_confirmacao_resposta(venda, parsed: dict) -> str:
    vid = venda.id
    if parsed.get('pode') is True:
        turno = parsed.get('turno')
        if turno == 'MANHA':
            resumo = 'Sim, manhã'
        elif turno == 'TARDE':
            resumo = 'Sim, tarde'
        else:
            resumo = 'Sim'
    elif parsed.get('pode') is False:
        resumo = 'Não'
    else:
        resumo = 'Recebida (formato não padrão)'
    return f'Resposta registrada para o pedido *#{vid}*: *{resumo}*. Obrigado!'


def formatar_posso_antecipar_exibicao(venda) -> str:
    """Texto exibido na coluna 'Posso antecipar?' da esteira (e no relatório Excel)."""
    if getattr(venda, 'vendedor_pode_antecipar', None) is True:
        turno = ''
        t = getattr(venda, 'vendedor_pode_antecipar_turno', None)
        if t == 'MANHA':
            turno = ', Manhã'
        elif t == 'TARDE':
            turno = ', Tarde'
        return f'Sim{turno}'
    if getattr(venda, 'vendedor_pode_antecipar', None) is False:
        return 'Não'
    if (
        getattr(venda, 'data_solicitacao_posso_antecipar', None)
        and not getattr(venda, 'data_resposta_posso_antecipar', None)
    ):
        return 'Aguardando'
    resp = (getattr(venda, 'vendedor_resposta_posso_antecipar', None) or '').strip()
    if resp:
        return resp
    return '-'


def _chaves_telefone_busca(telefone: str) -> list[str]:
    base = _normalizar_telefone_chave(telefone)
    if not base:
        return []
    chaves = [base]
    if base.startswith('55') and len(base) > 11:
        chaves.append(base[2:])
    elif len(base) >= 10:
        chaves.append('55' + base)
    nacional = base[2:] if base.startswith('55') and len(base) > 11 else base
    if len(nacional) == 10:
        chaves.append(nacional[:2] + '9' + nacional[2:])
    if len(nacional) == 11 and len(nacional) > 2 and nacional[2] == '9':
        chaves.append(nacional[:2] + nacional[3:])
    return list(dict.fromkeys(chaves))


def buscar_solicitacao_pendente_por_telefone(telefone: str, mensagem: str = ''):
    """Localiza solicitação pendente mais recente para o telefone do vendedor."""
    from datetime import timedelta

    from crm_app.models import PossoAnteciparVendedorEnviado

    chaves_norm = _chaves_telefone_busca(telefone)
    if not chaves_norm:
        return None

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_RESPOSTA)
    qs = (
        PossoAnteciparVendedorEnviado.objects.filter(
            telefone__in=chaves_norm,
            respondido_em__isnull=True,
            data_envio__gte=limite,
        )
        .select_related('venda', 'venda__vendedor')
        .order_by('-data_envio')
    )

    venda_id = _extrair_venda_id_da_mensagem(mensagem)
    if venda_id:
        sol = qs.filter(venda_id=venda_id).first()
        if sol:
            return sol

    return qs.first()


def listar_solicitacoes_pendentes_por_telefone(telefone: str, *, limite: int = 10):
    from datetime import timedelta

    from crm_app.models import PossoAnteciparVendedorEnviado

    chaves_norm = _chaves_telefone_busca(telefone)
    if not chaves_norm:
        return []

    limite_dt = timezone.now() - timedelta(hours=HORAS_LIMITE_RESPOSTA)
    return list(
        PossoAnteciparVendedorEnviado.objects.filter(
            telefone__in=chaves_norm,
            respondido_em__isnull=True,
            data_envio__gte=limite_dt,
        )
        .select_related('venda', 'venda__vendedor')
        .order_by('-data_envio')[:limite]
    )


def buscar_solicitacao_por_mensagem_whatsapp(reference_message_id: str, telefone: str = ''):
    """Localiza a consulta pelo messageId da mensagem com botões (identifica reenvios)."""
    from datetime import timedelta

    from crm_app.models import PossoAnteciparVendedorEnviado

    ref = (reference_message_id or '').strip()
    if not ref:
        return None

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_RESPOSTA)
    qs = (
        PossoAnteciparVendedorEnviado.objects.filter(
            whatsapp_message_id=ref,
            data_envio__gte=limite,
        )
        .select_related('venda', 'venda__vendedor')
        .order_by('-data_envio')
    )
    if telefone:
        chaves_norm = _chaves_telefone_busca(telefone)
        if chaves_norm:
            qs = qs.filter(telefone__in=chaves_norm)
    return qs.first()


def buscar_solicitacao_pendente_por_venda(venda_id: int, telefone: str):
    """Localiza solicitação pendente de um pedido específico (clique em botão)."""
    from datetime import timedelta

    from crm_app.models import PossoAnteciparVendedorEnviado

    chaves_norm = _chaves_telefone_busca(telefone)
    if not chaves_norm or not venda_id:
        return None

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_RESPOSTA)
    return (
        PossoAnteciparVendedorEnviado.objects.filter(
            venda_id=int(venda_id),
            telefone__in=chaves_norm,
            respondido_em__isnull=True,
            data_envio__gte=limite,
        )
        .select_related('venda', 'venda__vendedor')
        .order_by('-data_envio')
        .first()
    )


def registrar_resposta_posso_antecipar(solicitacao, mensagem: str = '', parsed: Optional[dict] = None) -> dict:
    """Grava resposta do vendedor na venda e marca solicitação como respondida."""
    if parsed is None:
        parsed = parse_resposta_posso_antecipar_vendedor(mensagem)
    agora = timezone.now()
    venda = solicitacao.venda

    campos = [
        'vendedor_pode_antecipar',
        'vendedor_pode_antecipar_turno',
        'vendedor_resposta_posso_antecipar',
        'vendedor_obs_posso_antecipar',
        'data_resposta_posso_antecipar',
    ]

    venda.vendedor_resposta_posso_antecipar = (parsed['resposta_completa'] or '')[:2000] or None
    venda.data_resposta_posso_antecipar = agora
    if parsed['pode'] is not None:
        venda.vendedor_pode_antecipar = parsed['pode']
    if parsed['turno']:
        venda.vendedor_pode_antecipar_turno = parsed['turno']
    if parsed['observacao']:
        venda.vendedor_obs_posso_antecipar = parsed['observacao']
    venda.save(update_fields=campos)

    solicitacao.respondido_em = agora
    solicitacao.save(update_fields=['respondido_em'])

    return parsed


def _enviar_whatsapp_posso_antecipar(telefone: str, venda) -> tuple[bool, str, str]:
    """Envia com botões REPLY (id por pedido); fallback texto se API falhar. Retorna (ok, texto, messageId)."""
    from crm_app.whatsapp_service import WhatsAppService

    mensagem = montar_mensagem_posso_antecipar(venda)
    botoes = montar_botoes_posso_antecipar(venda.id)
    svc = WhatsAppService()
    ok, resp = svc.enviar_mensagem_com_botoes_reply(
        telefone,
        mensagem,
        botoes,
        footer=f'Pedido #{venda.id}',
    )
    if ok:
        msg_id = _extrair_message_id_resposta_zapi(resp)
        return True, mensagem + '\n\n[Botões: Sim, manhã | Sim, tarde | Não]', msg_id
    ok_txt, _ = svc.enviar_mensagem_texto(
        telefone,
        mensagem + '\n\n(Responda: Sim, manhã | Sim, tarde | Não — inclua #' + str(venda.id) + ')',
        variar=False,
    )
    return bool(ok_txt), mensagem, ''


def tentar_enviar_posso_antecipar_vendedor(venda, *, usuario=None) -> dict:
    """
    Envia WhatsApp ao vendedor responsável pela venda.
    Retorna dict: ok, enviado, detail, mensagem.
    """
    from crm_app.models import PossoAnteciparVendedorEnviado

    resultado = {'ok': True, 'enviado': False, 'detail': '', 'mensagem': ''}

    st = (getattr(getattr(venda, 'status_esteira', None), 'nome', None) or '').upper()
    if 'AGENDADO' not in st:
        resultado['ok'] = False
        resultado['detail'] = 'Disponível apenas para vendas com status AGENDADO.'
        return resultado
    if not venda.data_agendamento:
        resultado['ok'] = False
        resultado['detail'] = 'Venda sem data de agendamento.'
        return resultado
    hoje = timezone.localdate()
    if venda.data_agendamento <= hoje:
        resultado['ok'] = False
        resultado['detail'] = 'Disponível apenas para agendamentos em dias futuros (após hoje).'
        return resultado

    if not getattr(venda, 'vendedor_id', None):
        resultado['ok'] = False
        resultado['detail'] = 'Venda sem vendedor vinculado.'
        return resultado

    telefone, err_tel = telefone_vendedor_para_envio_sistema(venda)
    if not telefone:
        resultado['ok'] = False
        resultado['detail'] = err_tel or 'Vendedor sem WhatsApp cadastrado.'
        return resultado

    mensagem = montar_mensagem_posso_antecipar(venda)
    resultado['mensagem'] = mensagem

    try:
        ok, mensagem_enviada, whatsapp_message_id = _enviar_whatsapp_posso_antecipar(telefone, venda)
        resultado['mensagem'] = mensagem_enviada
        if not ok:
            resultado['ok'] = False
            resultado['detail'] = 'Falha ao enviar mensagem (API WhatsApp).'
            return resultado

        tel_chave = _normalizar_telefone_chave(telefone)
        agora = timezone.now()
        PossoAnteciparVendedorEnviado.objects.create(
            telefone=tel_chave or telefone,
            venda=venda,
            vendedor=venda.vendedor,
            solicitado_por=usuario,
            whatsapp_message_id=whatsapp_message_id or '',
        )
        if whatsapp_message_id:
            logger.info(
                '[PossoAntecipar] Enviado venda #%s tel=%s messageId=%s',
                venda.id,
                tel_chave or telefone,
                whatsapp_message_id,
            )
        venda.data_solicitacao_posso_antecipar = agora
        venda.save(update_fields=['data_solicitacao_posso_antecipar'])

        resultado['enviado'] = True
        resultado['detail'] = 'Mensagem enviada ao vendedor.'
    except Exception as exc:
        resultado['ok'] = False
        resultado['detail'] = str(exc)
        logger.exception('Erro ao enviar posso antecipar venda #%s', venda.id)

    return resultado


def _mensagem_orientacao_multiplas_pendencias(pendentes) -> str:
    linhas = [
        'Você tem *várias* consultas "Posso antecipar?" pendentes.',
        'Toque no *botão da mensagem* do pedido correto (não digite só "Sim" ou "Não"):',
        '',
    ]
    for sol in pendentes[:5]:
        vid = sol.venda_id
        enviado = timezone.localtime(sol.data_envio).strftime('%d/%m %H:%M')
        linhas.append(f'• Pedido *#{vid}* — enviado em {enviado}')
    if len(pendentes) > 5:
        linhas.append(f'• … e mais {len(pendentes) - 5} consulta(s)')
    return '\n'.join(linhas)


def _parece_resposta_posso_antecipar(mensagem_texto: str, button_id: str = '') -> bool:
    if button_id and (button_id.startswith('pa_') or parse_button_id_posso_antecipar(button_id)):
        return True
    norm = _normalizar_texto_resposta(mensagem_texto)
    if re.match(r'^\s*SIM\b', norm) and re.search(r'\b(MANHA|TARDE)\b', norm):
        return True
    if re.match(r'^\s*NAO\b', norm):
        return True
    if re.match(r'^\s*SIM\b', norm) and len((mensagem_texto or '').strip()) <= 15:
        return True
    return False


def deve_tentar_posso_antecipar(
    mensagem_texto: str,
    *,
    button_id: str = '',
    reference_message_id: str = '',
    telefone: str = '',
) -> bool:
    """Evita consulta ao banco em mensagens do bot geral (Status, 1, O.S., etc.)."""
    if button_id and (button_id.startswith('pa_') or parse_button_id_posso_antecipar(button_id)):
        return True
    ref = (reference_message_id or '').strip()
    if ref and telefone:
        if buscar_solicitacao_por_mensagem_whatsapp(ref, telefone):
            return True
    if _extrair_venda_id_da_mensagem(mensagem_texto or ''):
        return True
    return _parece_resposta_posso_antecipar(mensagem_texto or '', button_id)


def processar_resposta_posso_antecipar_vendedor(
    telefone_remetente,
    mensagem_texto,
    *,
    button_id: str = '',
    reference_message_id: str = '',
) -> bool:
    """
    Se o vendedor respondeu (botão ou texto) a uma consulta pendente, registra e confirma.

    Identificação do pedido (prioridade):
    1. referenceMessageId — mensagem WhatsApp com botões (funciona em reenvios)
    2. buttonId pa_{venda_id}_* — botão com id do pedido
    3. Texto com #pedido ou única consulta pendente para o telefone
    """
    btn_parsed = parse_button_id_posso_antecipar(button_id) if button_id else None
    solicitacao = None
    parsed = None
    ref = (reference_message_id or '').strip()

    if not deve_tentar_posso_antecipar(
        mensagem_texto or '',
        button_id=button_id,
        reference_message_id=ref,
        telefone=telefone_remetente,
    ):
        return False

    logger.info(
        '[PossoAntecipar] Processando tel=%s btn=%r ref=%r msg=%r',
        telefone_remetente,
        button_id or '-',
        ref or '-',
        (mensagem_texto or '')[:80],
    )

    try:
        return _processar_resposta_posso_antecipar_vendedor_impl(
            telefone_remetente,
            mensagem_texto,
            button_id=button_id,
            reference_message_id=ref,
            btn_parsed=btn_parsed,
        )
    except Exception as exc:
        from django.db.utils import ProgrammingError
        if isinstance(exc, ProgrammingError) and 'whatsapp_message_id' in str(exc):
            logger.error(
                '[PossoAntecipar] Migration 0145 pendente (coluna whatsapp_message_id). '
                'Execute: python manage.py migrate'
            )
            return False
        raise


def _processar_resposta_posso_antecipar_vendedor_impl(
    telefone_remetente,
    mensagem_texto,
    *,
    button_id: str = '',
    reference_message_id: str = '',
    btn_parsed=None,
) -> bool:
    solicitacao = None
    parsed = None
    ref = (reference_message_id or '').strip()
    if btn_parsed is None and button_id:
        btn_parsed = parse_button_id_posso_antecipar(button_id)

    if ref:
        solicitacao = buscar_solicitacao_por_mensagem_whatsapp(ref, telefone_remetente)
        if solicitacao and solicitacao.respondido_em:
            try:
                from crm_app.whatsapp_service import WhatsAppService
                from crm_app.whatsapp_webhook_handler import formatar_telefone

                tel = formatar_telefone(telefone_remetente)
                if tel:
                    WhatsAppService().enviar_mensagem_texto(
                        tel,
                        f'Este pedido *#{solicitacao.venda_id}* já foi respondido. '
                        'Se precisar alterar, avise o backoffice.',
                        variar=False,
                    )
                return True
            except Exception:
                logger.exception('[PossoAntecipar] Erro ao avisar pedido já respondido')
            return True

    if btn_parsed:
        if solicitacao is None or solicitacao.venda_id != btn_parsed['venda_id']:
            sol_btn = buscar_solicitacao_pendente_por_venda(
                btn_parsed['venda_id'], telefone_remetente,
            )
            if sol_btn:
                solicitacao = sol_btn
        parsed = btn_parsed
    elif solicitacao is None and (mensagem_texto or '').strip():
        pendentes = listar_solicitacoes_pendentes_por_telefone(telefone_remetente)
        venda_id_msg = _extrair_venda_id_da_mensagem(mensagem_texto)
        if venda_id_msg:
            solicitacao = next((s for s in pendentes if s.venda_id == venda_id_msg), None)
        elif len(pendentes) == 1:
            solicitacao = pendentes[0]
        elif len(pendentes) > 1 and _parece_resposta_posso_antecipar(mensagem_texto, button_id):
            try:
                from crm_app.whatsapp_service import WhatsAppService
                from crm_app.whatsapp_webhook_handler import formatar_telefone

                tel = formatar_telefone(telefone_remetente)
                if tel:
                    WhatsAppService().enviar_mensagem_texto(
                        tel,
                        _mensagem_orientacao_multiplas_pendencias(pendentes),
                        variar=False,
                    )
                return True
            except Exception:
                logger.exception('[PossoAntecipar] Erro ao orientar múltiplas pendências')
            return True
        else:
            solicitacao = buscar_solicitacao_pendente_por_telefone(telefone_remetente, mensagem_texto)

    if not solicitacao:
        if btn_parsed or ref:
            try:
                from crm_app.whatsapp_service import WhatsAppService
                from crm_app.whatsapp_webhook_handler import formatar_telefone

                tel = formatar_telefone(telefone_remetente)
                if tel:
                    det = (
                        f'pedido *#{btn_parsed["venda_id"]}*'
                        if btn_parsed
                        else 'consulta vinculada a esta mensagem'
                    )
                    WhatsAppService().enviar_mensagem_texto(
                        tel,
                        f'Não encontrei {det} pendente. Pode ter expirado ou já foi respondida.',
                        variar=False,
                    )
                return True
            except Exception:
                logger.exception('[PossoAntecipar] Erro ao avisar consulta expirada')
        return False

    if parsed is None and not (mensagem_texto or '').strip() and not btn_parsed:
        return False

    try:
        if parsed is None:
            parsed = parse_resposta_posso_antecipar_vendedor(mensagem_texto)

        # Observação em texto livre (não fecha consulta se ainda não houve Sim/Não)
        if parsed.get('pode') is None and solicitacao.respondido_em is None:
            obs = (parsed.get('observacao') or mensagem_texto or '').strip()
            if obs and len(obs) > 20:
                logger.info(
                    '[PossoAntecipar] Texto livre ignorado como resposta (aguardando botão/Sim/Não) venda #%s',
                    solicitacao.venda_id,
                )
                return False

        # Complemento após resposta já registrada
        if parsed.get('pode') is None and solicitacao.respondido_em:
            obs = (parsed.get('observacao') or mensagem_texto or '').strip()
            if obs:
                venda = solicitacao.venda
                atual = (getattr(venda, 'vendedor_obs_posso_antecipar', None) or '').strip()
                nova = f'{atual}\n{obs}'.strip() if atual else obs
                venda.vendedor_obs_posso_antecipar = nova[:2000]
                venda.save(update_fields=['vendedor_obs_posso_antecipar'])
                logger.info('[PossoAntecipar] Observação adicionada venda #%s', solicitacao.venda_id)
            return True

        if parsed.get('pode') is None:
            return False

        texto_gravacao = (parsed.get('resposta_completa') or mensagem_texto or '').strip()
        registrar_resposta_posso_antecipar(solicitacao, texto_gravacao, parsed=parsed)

        from crm_app.whatsapp_service import WhatsAppService
        from crm_app.whatsapp_webhook_handler import formatar_telefone

        msg = _mensagem_confirmacao_resposta(solicitacao.venda, parsed)
        tel = formatar_telefone(telefone_remetente)
        if tel:
            WhatsAppService().enviar_mensagem_texto(tel, msg, variar=False)
        logger.info(
            '[PossoAntecipar] Resposta registrada venda #%s: pode=%s turno=%s botao=%s ref=%s',
            solicitacao.venda_id,
            parsed.get('pode'),
            parsed.get('turno'),
            button_id or '-',
            ref or '-',
        )
        return True
    except Exception:
        logger.exception('[PossoAntecipar] Erro ao processar resposta do vendedor')
        return False
