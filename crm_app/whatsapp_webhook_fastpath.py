"""
Filtro leve para webhooks WhatsApp (Z-API / Evolution): descarta ruido antes do handler.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from crm_app.whatsapp_webhook_normalizer import detectar_provedor, normalizar_webhook

logger = logging.getLogger(__name__)

# Mesmo critério simplificado de antecipar_instalacao_utils.parse_mensagem_resposta_gc_antecipar
_RE_POSSIVEL_RESPOSTA_GC = re.compile(
    r'(?:O\.?S\.?)?\s*\d+\s*[,]?\s*(?:(?:nao|não)\s*antecipada|antecipada|solicitado)',
    re.IGNORECASE,
)

_TIPOS_PROCESSAR = frozenset({
    '',
    'receivedcallback',
    'message',
    'messages',
})

_CHAVES_MIDIA = frozenset({
    'image', 'imageUrl', 'document', 'documentUrl', 'audio', 'video', 'sticker',
})


def _extrair_texto_minimo(data: Dict[str, Any]) -> str:
    mensagem = ''
    text_obj = data.get('text')
    if isinstance(text_obj, dict):
        mensagem = (
            text_obj.get('message')
            or text_obj.get('text')
            or text_obj.get('body')
            or ''
        )
    if not mensagem:
        msg_obj = data.get('message')
        if isinstance(msg_obj, dict):
            mensagem = (
                msg_obj.get('text')
                or msg_obj.get('body')
                or msg_obj.get('message')
                or ''
            )
        elif msg_obj is not None:
            mensagem = str(msg_obj)
    if not mensagem:
        mensagem = data.get('body') or data.get('content') or ''
        if not mensagem and not isinstance(data.get('text'), dict):
            raw = data.get('text')
            if isinstance(raw, str):
                mensagem = raw
    if isinstance(mensagem, dict):
        mensagem = (
            mensagem.get('message')
            or mensagem.get('text')
            or mensagem.get('body')
            or ''
        )
    return (mensagem or '').strip()


def _telefone_bruto(data: Dict[str, Any]) -> str:
    telefone = (
        data.get('phone')
        or data.get('from')
        or data.get('phoneNumber')
        or data.get('phone_number')
        or ''
    )
    if not telefone and isinstance(data.get('text'), dict):
        telefone = data['text'].get('participant') or ''
    if not telefone and isinstance(data.get('message'), dict):
        telefone = (data.get('message') or {}).get('participant') or ''
    return str(telefone or '')


def _from_me(data: Dict[str, Any]) -> bool:
    from_me = data.get('fromMe') or data.get('isFromMe') or data.get('from_me')
    if not from_me and isinstance(data.get('message'), dict):
        msg = data['message']
        from_me = msg.get('fromMe') or msg.get('isFromMe') or msg.get('from_me')
    return bool(from_me)


def _is_group(data: Dict[str, Any], telefone: str) -> bool:
    return bool(
        data.get('isGroup')
        or ('-group' in telefone)
        or ('@g.us' in telefone)
    )


def _tem_midia(data: Dict[str, Any]) -> bool:
    if any(k in data for k in _CHAVES_MIDIA):
        return True
    for key in ('image', 'document', 'audio', 'video'):
        val = data.get(key)
        if isinstance(val, dict) and val:
            return True
    return False


def _parece_resposta_gc(texto: str) -> bool:
    if not texto:
        return False
    primeira_linha = texto.strip().splitlines()[0] if texto else ''
    return bool(_RE_POSSIVEL_RESPOSTA_GC.search(primeira_linha))


def _tem_referencia_ou_clique_botao(data: Any, _depth: int = 0) -> bool:
    """
    Clique em botão Z-API (send-button-actions) costuma chegar sem texto no payload.
    Não descartar no fastpath — o handler completo extrai buttonId/referenceMessageId.
    """
    if _depth > 8 or not isinstance(data, dict):
        return False
    for key in ('referenceMessageId', 'quotedMessageId', 'quotedMsgId', 'referenceMsgId'):
        if data.get(key):
            return True
    for key in (
        'buttonsResponseMessage',
        'buttonResponseMessage',
        'buttonActionsResponseMessage',
        'templateButtonReplyMessage',
        'nativeFlowResponseMessage',
        'interactiveResponseMessage',
        'buttonReply',
        'replyButton',
    ):
        if isinstance(data.get(key), dict):
            return True
    if any(data.get(k) for k in ('buttonId', 'selectedButtonId', 'selectedId')):
        return True
    for nested in ('message', 'data', 'payload', 'text'):
        sub = data.get(nested)
        if isinstance(sub, dict) and _tem_referencia_ou_clique_botao(sub, _depth + 1):
            return True
    return False


def avaliar_fastpath_webhook(data: Any) -> Optional[Dict[str, str]]:
    """
    Retorna resposta HTTP (status/mensagem) para encerrar sem o handler completo.
    None = continuar processamento normal.
    """
    if isinstance(data, dict) and detectar_provedor(data) == "evolution":
        data = normalizar_webhook(data)
    return avaliar_fastpath_zapi(data)


def avaliar_fastpath_zapi(data: Any) -> Optional[Dict[str, str]]:
    """
    Retorna resposta HTTP (status/mensagem) para encerrar sem o handler completo.
    None = continuar processamento normal.
    """
    if not isinstance(data, dict) or not data:
        return {'status': 'ok', 'mensagem': 'Payload vazio'}

    if _from_me(data):
        return {'status': 'ok', 'mensagem': 'Ignorando mensagem do próprio bot'}

    if data.get('isNewsletter'):
        return {'status': 'ok', 'mensagem': 'Newsletter ignorada'}

    if data.get('isStatusReply'):
        return {'status': 'ok', 'mensagem': 'Status reply ignorado'}

    if data.get('isEdit'):
        return {'status': 'ok', 'mensagem': 'Edição ignorada'}

    tipo = str(data.get('type') or '').strip().lower()
    if tipo and tipo not in _TIPOS_PROCESSAR:
        return {'status': 'ok', 'mensagem': f'Evento {tipo} ignorado'}

    telefone = _telefone_bruto(data)
    texto = _extrair_texto_minimo(data)
    tem_midia = _tem_midia(data)

    from crm_app.whatsapp_telefone_blocklist import telefone_esta_bloqueado

    participant = (
        data.get('participantPhone')
        or data.get('participant_phone')
        or ''
    )
    if isinstance(data.get('text'), dict) and not participant:
        participant = data['text'].get('participant') or ''
    if isinstance(data.get('message'), dict) and not participant:
        participant = (data.get('message') or {}).get('participant') or ''
    if telefone_esta_bloqueado(telefone) or telefone_esta_bloqueado(str(participant)):
        logger.info("[Fastpath] Telefone bloqueado ignorado: %s", telefone or participant)
        return {'status': 'ok', 'mensagem': 'Telefone bloqueado'}

    if _is_group(data, telefone):
        if texto and _parece_resposta_gc(texto):
            return None
        return {'status': 'ok', 'mensagem': 'Mensagem de grupo ignorada'}

    if 'reaction' in data and not texto and not tem_midia:
        return {'status': 'ok', 'mensagem': 'Reação ignorada'}

    if not telefone and not tem_midia:
        return {'status': 'ok', 'mensagem': 'Webhook sem telefone/mídia ignorado'}

    if not texto and not tem_midia:
        if _tem_referencia_ou_clique_botao(data):
            return None
        return {'status': 'ok', 'mensagem': 'Webhook sem conteúdo ignorado'}

    return None
