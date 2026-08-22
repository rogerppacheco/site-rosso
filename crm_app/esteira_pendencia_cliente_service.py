"""Envio automático de WhatsApp ao cliente quando pendência tipo CLIENTE é registrada na esteira."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

NIO_WHATSAPP_OFICIAL = '21 3605-1000'


def _normalizar_tipo_pendencia(tipo: str) -> str:
    if not tipo:
        return ''
    nfd = unicodedata.normalize('NFD', str(tipo).strip().upper())
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')


def is_motivo_pendencia_tipo_cliente(motivo) -> bool:
    if not motivo:
        return False
    return 'CLIENTE' in _normalizar_tipo_pendencia(getattr(motivo, 'tipo_pendencia', '') or '')


def venda_em_status_pendente(venda) -> bool:
    status = getattr(venda, 'status_esteira', None)
    if not status:
        return False
    nome = (getattr(status, 'nome', '') or '').upper()
    return 'PENDEN' in nome or 'PENDÊN' in nome


def _primeiro_nome(texto: str, padrao: str = '') -> str:
    nome = (texto or '').strip()
    if not nome:
        return padrao
    return nome.split()[0]


def _primeiro_nome_usuario(usuario) -> str:
    if not usuario:
        return 'Especialista'
    nome = (getattr(usuario, 'first_name', None) or '').strip()
    if nome:
        return _primeiro_nome(nome, 'Especialista')
    username = (getattr(usuario, 'username', None) or '').strip()
    return _primeiro_nome(username, 'Especialista')


def _formatar_telefone_exibicao(telefone: str) -> str:
    """Formata para exibição na mensagem (ex.: (21) 99999-8888)."""
    dig = re.sub(r'\D', '', str(telefone or ''))
    if dig.startswith('55') and len(dig) > 11:
        dig = dig[2:]
    if len(dig) == 11:
        return f'({dig[:2]}) {dig[2:7]}-{dig[7:]}'
    if len(dig) == 10:
        return f'({dig[:2]}) {dig[2:6]}-{dig[6:]}'
    return (telefone or '').strip()


def _telefone_br_digitos_api(telefone: str) -> Optional[str]:
    """DDI 55 + número (somente dígitos) para wa.me e botões Z-API."""
    dig = re.sub(r'\D', '', str(telefone or ''))
    if not dig:
        return None
    if dig.startswith('55') and len(dig) >= 12:
        return dig
    if len(dig) in (10, 11):
        return '55' + dig
    if len(dig) >= 12:
        return dig
    return None


def _telefone_raw_backoffice() -> Optional[str]:
    """WhatsApp BackOffice configurado na esteira (singleton)."""
    from crm_app.esteira_config_utils import get_esteira_vendas_config

    tel = (get_esteira_vendas_config().whatsapp_backoffice or '').strip()
    return tel or None


def _whatsapp_backoffice_exibicao() -> Optional[str]:
    """Telefone formatado para exibição em texto (fallback sem botão)."""
    tel = _telefone_raw_backoffice()
    return _formatar_telefone_exibicao(tel) if tel else None


def montar_botoes_pendencia_cliente(venda=None) -> list:
    """
    Botões Z-API (send-button-actions): abre o WhatsApp do BackOffice ao tocar.
    Tipo URL + wa.me — mais adequado que CALL para contato via WhatsApp.
    """
    dig = _telefone_br_digitos_api(_telefone_raw_backoffice() or '')
    if not dig:
        return []
    return [{
        'id': 'pend_backoffice_duvidas',
        'type': 'URL',
        'label': 'Dúvidas (BackOffice)',
        'url': f'https://wa.me/{dig}',
    }]


def montar_mensagem_reagendamento_pendencia_cliente(
    venda, usuario=None, *, usar_botao_parceiro: bool = False,
) -> str:
    """
    Texto alinhado ao manual da jornada do cliente (tom cordial, sem culpar o cliente,
    canais oficiais Nio + atendimento do parceiro para dúvidas).
    """
    agora = timezone.now()
    saudacao = 'boa tarde' if agora.hour >= 12 else 'bom dia'
    nome_completo = ''
    if getattr(venda, 'cliente', None):
        nome_completo = (venda.cliente.nome_razao_social or '').strip()
    nome_cliente = _primeiro_nome(nome_completo, 'Cliente')
    especialista = _primeiro_nome_usuario(usuario)
    whatsapp_backoffice = _whatsapp_backoffice_exibicao()

    linhas = [
        f'Olá, {saudacao} Sr(a). {nome_cliente}',
        '',
        f'Me chamo {especialista}, sou especialista de qualidade na Nio Fibra.',
        '',
        'Identificamos uma pendência no agendamento da sua instalação Nio Fibra. '
        'Na maioria dos casos isso não depende de você.',
        '',
        f'Para reagendar, entre em contato pelo WhatsApp oficial da Nio: {NIO_WHATSAPP_OFICIAL}.',
    ]
    if whatsapp_backoffice:
        if usar_botao_parceiro:
            linhas.extend([
                '',
                'Para dúvidas sobre seu pedido, toque no botão abaixo.',
            ])
        else:
            linhas.extend([
                '',
                f'Para dúvidas sobre seu pedido, fale com o atendimento BackOffice pelo WhatsApp: {whatsapp_backoffice}.',
            ])
    linhas.extend(['', 'Obrigado por escolher a Nio Fibra.'])
    return '\n'.join(linhas)


def _enviar_whatsapp_pendencia_cliente(telefone: str, venda, usuario) -> tuple[bool, str]:
    """
    Prefere template Meta (nio_pendencia_reagendamento_v1); se falhar/desabilitado,
    tenta botão URL (BackOffice) e por fim texto livre.
    Retorna (sucesso, mensagem_final_enviada).
    """
    from crm_app.services.whatsapp.nio_templates import (
        enviar_pendencia_reagendamento,
        templates_habilitados,
    )
    from crm_app.whatsapp_service import WhatsAppService

    nome_cliente = ''
    if getattr(venda, 'cliente', None):
        nome_cliente = (venda.cliente.nome_razao_social or '').strip()

    mensagem_txt = montar_mensagem_reagendamento_pendencia_cliente(
        venda, usuario, usar_botao_parceiro=False,
    )

    if templates_habilitados():
        ok, _resp, canal = enviar_pendencia_reagendamento(
            telefone, nome_cliente, mensagem_txt,
        )
        if ok and canal == 'template':
            return True, (
                f'[template nio_pendencia_reagendamento_v1]\n{mensagem_txt}'
            )
        if ok:
            return True, mensagem_txt

    svc = WhatsAppService.para_cliente()
    botoes = montar_botoes_pendencia_cliente(venda)
    if botoes:
        mensagem_btn = montar_mensagem_reagendamento_pendencia_cliente(
            venda, usuario, usar_botao_parceiro=True,
        )
        ok, _ = svc.enviar_mensagem_com_botoes_reply(telefone, mensagem_btn, botoes)
        if ok:
            return True, mensagem_btn + '\n\n[Botão: Dúvidas (BackOffice)]'

    ok, _ = svc.enviar_mensagem_texto(telefone, mensagem_txt)
    return bool(ok), mensagem_txt


def _normalizar_telefone_chave(telefone: str) -> str:
    if not telefone:
        return ''
    tel = re.sub(r'\D', '', str(telefone))
    if tel.startswith('55') and len(tel) > 12:
        tel = tel[2:]
    return tel


def tentar_enviar_msg_pendencia_cliente(
    venda,
    motivo,
    *,
    usuario=None,
    enviar_whatsapp: bool = True,
) -> dict:
    """
    Envia mensagem ao telefone1 da venda quando motivo é tipo CLIENTE.
    Retorna dict: ok, enviado, detail, mensagem.
    """
    from crm_app.models import HistoricoAtendimentoIACliente, PendenciaClienteMsgEnviada

    resultado = {'ok': True, 'enviado': False, 'detail': '', 'mensagem': ''}

    if not enviar_whatsapp:
        resultado['detail'] = 'Envio WhatsApp desativado na esteira.'
        return resultado

    if not is_motivo_pendencia_tipo_cliente(motivo):
        resultado['detail'] = 'Motivo não é do tipo CLIENTE.'
        return resultado

    if not venda_em_status_pendente(venda):
        resultado['detail'] = 'Venda não está com status pendente.'
        return resultado

    telefone = (getattr(venda, 'telefone1', None) or '').strip()
    if not telefone:
        resultado['ok'] = False
        resultado['detail'] = 'Telefone do cliente não informado na venda.'
        return resultado

    if PendenciaClienteMsgEnviada.objects.filter(
        venda=venda, motivo_pendencia=motivo, sucesso=True,
    ).exists():
        resultado['detail'] = 'Mensagem já enviada para este motivo de pendência.'
        return resultado

    registro = PendenciaClienteMsgEnviada(
        venda=venda,
        motivo_pendencia=motivo,
        telefone=telefone,
        mensagem='',
        usuario=usuario,
        sucesso=False,
    )

    try:
        ok, mensagem = _enviar_whatsapp_pendencia_cliente(telefone, venda, usuario)
        resultado['mensagem'] = mensagem
        registro.mensagem = mensagem
        registro.sucesso = bool(ok)
        registro.save()

        if ok:
            resultado['enviado'] = True
            resultado['detail'] = 'Mensagem enviada ao cliente.'
            tel_chave = _normalizar_telefone_chave(telefone)
            try:
                HistoricoAtendimentoIACliente.objects.create(
                    venda=venda,
                    telefone=tel_chave or telefone,
                    mensagem_cliente='[Sistema] Pendência tipo CLIENTE registrada na esteira',
                    resposta_sistema=mensagem,
                    intencao='AGENDAMENTO',
                    fonte_resposta='TEMPLATE',
                    origem='PENDENCIA_CLIENTE',
                )
            except Exception:
                logger.exception('Erro ao gravar histórico atendimento pendência cliente')
            try:
                from crm_app.esteira_eventos_utils import (
                    ORIGEM_SISTEMA,
                    TIPO_MSG_CLIENTE_PENDENCIA,
                    criar_evento_esteira,
                    salvar_eventos_esteira,
                )

                ev = criar_evento_esteira(
                    venda_id=venda.id,
                    tipo_evento=TIPO_MSG_CLIENTE_PENDENCIA,
                    valor_anterior='',
                    valor_novo=motivo.nome if motivo else '',
                    origem=ORIGEM_SISTEMA,
                    usuario=usuario,
                    motivo_pendencia_id=motivo.id if motivo else None,
                )
                salvar_eventos_esteira([ev] if ev else [])
            except Exception:
                logger.exception('Erro ao registrar evento esteira MSG cliente pendência')
        else:
            resultado['ok'] = False
            resultado['detail'] = 'Falha ao enviar mensagem (API WhatsApp).'
    except Exception as exc:
        registro.erro = str(exc)[:500]
        registro.save()
        resultado['ok'] = False
        resultado['detail'] = str(exc)
        logger.exception('Erro ao enviar msg pendência cliente venda #%s', venda.id)

    return resultado
