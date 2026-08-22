"""
Normaliza webhooks Z-API, Evolution e WhatsAtende para formato canonico
consumido pelo handler.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_PROVEDOR_ZAPI = "zapi"
_PROVEDOR_EVOLUTION = "evolution"
_PROVEDOR_WHATSATENDE = "whatsatende"

_WHATSATENDE_EVENTS_INBOUND = frozenset(
    {
        "message.received",
        "messages.received",
        "message.create",
        "message.created",
        "chat.message",
        "ticket.message",
    }
)
_WHATSATENDE_EVENTS_STATUS = frozenset(
    {
        "message.status",
        "messages.status",
        "message.update",
        "message.ack",
        "message.sent",
        "message.delivered",
        "message.read",
        "message.failed",
        "messages.failed",
    }
)


def _eh_webhook_cloud_api_meta(payload: Dict[str, Any]) -> bool:
    if payload.get("object") == "whatsapp_business_account":
        return True
    entry = payload.get("entry")
    if not isinstance(entry, list) or not entry:
        return False
    first = entry[0]
    if not isinstance(first, dict):
        return False
    changes = first.get("changes")
    if not isinstance(changes, list) or not changes:
        return False
    change0 = changes[0]
    if not isinstance(change0, dict):
        return False
    value = change0.get("value")
    if not isinstance(value, dict):
        return False
    return bool(value.get("statuses"))


def extrair_callbacks_status(payload: Any) -> list:
    """
    Extrai DeliveryCallback / MessageStatusCallback de:
    - Z-API (type já canônico)
    - WhatsAtende event=message.failed / message.status
    - Cloud API Meta (object=whatsapp_business_account + statuses)
    """
    if not isinstance(payload, dict):
        return []

    tipo = str(payload.get("type") or "").strip().lower()
    if tipo == "deliverycallback":
        return [payload]
    if tipo == "messagestatuscallback":
        return [payload]

    if _eh_webhook_cloud_api_meta(payload):
        return _callbacks_from_meta_cloud(payload)

    nested = payload.get("data")
    if isinstance(nested, dict) and (
        _eh_webhook_cloud_api_meta(nested) or nested.get("statuses")
    ):
        if nested.get("statuses") and not _eh_webhook_cloud_api_meta(nested):
            return _callbacks_from_statuses_lista(
                nested.get("statuses"),
                phone=_digitos_telefone(
                    nested.get("recipient_id")
                    or payload.get("senderNumber")
                    or payload.get("phone")
                ),
            )
        return _callbacks_from_meta_cloud(nested)

    evento = str(payload.get("event") or "").lower()
    if evento in _WHATSATENDE_EVENTS_STATUS:
        cb = _callback_from_whatsatende_status(payload)
        return [cb] if cb else []

    # Payload misto: id + errors[] (Cloud API / WhatsAtende)
    if payload.get("errors") and (
        payload.get("id") or payload.get("messageId") or payload.get("wamid")
    ):
        cb = _callback_from_whatsatende_status({**payload, "event": "message.failed"})
        return [cb] if cb else []

    return []


def _callbacks_from_meta_cloud(payload: Dict[str, Any]) -> list:
    out: list = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            statuses = value.get("statuses")
            if not isinstance(statuses, list):
                continue
            out.extend(_callbacks_from_statuses_lista(statuses))
    return out


def _callbacks_from_statuses_lista(statuses: Any, phone: str = "") -> list:
    out: list = []
    if not isinstance(statuses, list):
        return out
    for st in statuses:
        if not isinstance(st, dict):
            continue
        mid = st.get("id") or st.get("messageId") or st.get("wamid")
        status_raw = str(st.get("status") or "").strip().lower()
        dest = phone or _digitos_telefone(
            st.get("recipient_id") or st.get("recipientId") or st.get("phone")
        )
        errors = st.get("errors") if isinstance(st.get("errors"), list) else []
        err0 = errors[0] if errors and isinstance(errors[0], dict) else {}
        code = err0.get("code")
        details = ""
        err_data = err0.get("error_data")
        if isinstance(err_data, dict):
            details = str(err_data.get("details") or "").strip()
        err_msg = (
            details
            or str(err0.get("message") or "").strip()
            or str(err0.get("title") or "").strip()
        )
        if status_raw in ("failed", "error", "fail") or errors:
            out.append(
                {
                    "type": "DeliveryCallback",
                    "messageId": mid,
                    "phone": dest,
                    "error": err_msg or "falha de entrega",
                    "errorCode": str(code) if code is not None else "",
                    "errors": errors,
                    "_meta_status": status_raw,
                }
            )
            continue
        mapped = "SENT"
        if status_raw in ("delivered", "delivery_ack"):
            mapped = "RECEIVED"
        elif status_raw in ("read", "played"):
            mapped = "READ"
        elif status_raw in ("sent", "server"):
            mapped = "SENT"
        else:
            continue
        out.append(
            {
                "type": "MessageStatusCallback",
                "ids": [mid] if mid else [],
                "messageId": mid,
                "status": mapped,
                "phone": dest,
                "_meta_status": status_raw,
            }
        )
    return out


def _callback_from_whatsatende_status(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mid = (
        payload.get("messageId")
        or payload.get("id")
        or payload.get("wamid")
    )
    phone = _digitos_telefone(
        payload.get("senderNumber")
        or payload.get("recipient_id")
        or payload.get("number")
        or payload.get("phone")
    )
    status_raw = str(
        payload.get("ackStatus")
        or payload.get("deliveryStatus")
        or payload.get("status")
        or payload.get("event")
        or ""
    ).lower()
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    code = payload.get("errorCode") or payload.get("error_code") or payload.get("code")
    if errors and isinstance(errors[0], dict) and not code:
        code = errors[0].get("code")
    err_msg = payload.get("error") or payload.get("message")
    if isinstance(err_msg, dict):
        err_msg = err_msg.get("message") or err_msg.get("title") or str(err_msg)
    failed_tokens = (
        "failed",
        "error",
        "fail",
        "message.failed",
        "messages.failed",
    )
    if status_raw in failed_tokens or errors or payload.get("error"):
        return {
            "type": "DeliveryCallback",
            "messageId": mid,
            "phone": phone,
            "error": str(err_msg or "falha de entrega"),
            "errorCode": str(code) if code is not None else "",
            "errors": errors,
            "_whatsatende_raw": payload,
        }
    if status_raw in (
        "delivered",
        "delivery_ack",
        "read",
        "played",
        "message.delivered",
        "message.read",
        "sent",
        "message.sent",
    ):
        mapped = "SENT"
        if "read" in status_raw or status_raw == "played":
            mapped = "READ"
        elif "deliver" in status_raw:
            mapped = "RECEIVED"
        return {
            "type": "MessageStatusCallback",
            "ids": [mid] if mid else [],
            "messageId": mid,
            "status": mapped,
            "phone": phone,
            "_whatsatende_raw": payload,
        }
    evento = str(payload.get("event") or "").lower()
    if evento in ("message.failed", "messages.failed"):
        return {
            "type": "DeliveryCallback",
            "messageId": mid,
            "phone": phone,
            "error": str(err_msg or "falha de entrega"),
            "errorCode": str(code) if code is not None else "",
            "errors": errors,
            "_whatsatende_raw": payload,
        }
    return None


def detectar_provedor(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _PROVEDOR_ZAPI

    if _eh_webhook_cloud_api_meta(payload):
        return _PROVEDOR_WHATSATENDE

    source = str(
        payload.get("source")
        or payload.get("provider")
        or payload.get("origem")
        or ""
    ).lower()
    if "whatsatende" in source or "souchat" in source:
        return _PROVEDOR_WHATSATENDE

    # Payload oficial app14 (suporte 2026-07-31): senderNumber + id/ticketId
    if payload.get("senderNumber") and (
        payload.get("id") is not None or payload.get("ticketId") is not None
    ):
        return _PROVEDOR_WHATSATENDE

    evento = str(payload.get("event") or "").lower()
    if evento in ("messages.upsert", "messages.update", "send.message"):
        return _PROVEDOR_EVOLUTION
    if payload.get("data") and isinstance(payload.get("data"), dict):
        data = payload["data"]
        if isinstance(data.get("key"), dict) and "remoteJid" in data["key"]:
            return _PROVEDOR_EVOLUTION

    if evento in _WHATSATENDE_EVENTS_INBOUND or evento in _WHATSATENDE_EVENTS_STATUS:
        return _PROVEDOR_WHATSATENDE

    # Formato legado SouChat: contact + message (objetos)
    contact = payload.get("contact")
    message = payload.get("message")
    if isinstance(contact, dict) and isinstance(message, dict):
        if contact.get("number") or contact.get("phone"):
            return _PROVEDOR_WHATSATENDE

    if payload.get("phone") or payload.get("type") == "ReceivedCallback":
        return _PROVEDOR_ZAPI
    return _PROVEDOR_ZAPI


def normalizar_webhook(payload: Any) -> Dict[str, Any]:
    """Retorna payload canonico (compativel com handler Z-API existente)."""
    if not isinstance(payload, dict):
        return {}
    provedor = detectar_provedor(payload)
    if provedor == _PROVEDOR_EVOLUTION:
        return _normalizar_evolution(payload)
    if provedor == _PROVEDOR_WHATSATENDE:
        return _normalizar_whatsatende(payload)
    return payload


def _digitos_telefone(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    for suffix in ("@s.whatsapp.net", "@c.us", "@g.us"):
        if suffix in s:
            s = s.split(suffix)[0]
    return "".join(ch for ch in s if ch.isdigit())


def _normalizar_whatsatende(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload oficial app14 (webhook de mensagem recebida/enviada).

    Exemplo resumido:
    {
      "id": "wamid....",
      "type": "text"|"image"|...,
      "message": "texto",
      "mediaUrl": null|"https://...",
      "mediaType": null|"image/jpeg",
      "senderNumber": "5531...",
      "ticketId": 12345,
      "status": "open",   # status do ticket, NÃO ACK de entrega
      "userId": null|7,   # null = cliente; preenchido = enviado pela plataforma/API
      "queueId": 10
    }

    Não existe webhook público de entregue/lida/falha — não gerar DeliveryCallback
    a partir de status de ticket.
    """
    evento = str(payload.get("event") or "").lower()

    # ACK explícito (hoje a WhatsAtende não documenta; manter se o suporte ativar)
    if evento in _WHATSATENDE_EVENTS_STATUS:
        cb = _callback_from_whatsatende_status(payload)
        if cb:
            return cb

    # Payload bruto opcional (sendMsgWhatsapp): objeto original em "msg"
    msg_bruto = payload.get("msg") if isinstance(payload.get("msg"), dict) else {}

    # Formato oficial: message é string; legado: message é objeto
    message_field = payload.get("message")
    if isinstance(message_field, str):
        texto = message_field.strip()
        message_obj: Dict[str, Any] = {}
    elif isinstance(message_field, dict):
        message_obj = message_field
        texto = str(
            message_obj.get("body")
            or message_obj.get("text")
            or message_obj.get("message")
            or ""
        ).strip()
    else:
        message_obj = {}
        texto = str(payload.get("body") or "").strip()

    if not texto and msg_bruto:
        texto = str(
            msg_bruto.get("conversation")
            or (msg_bruto.get("extendedTextMessage") or {}).get("text")
            or msg_bruto.get("body")
            or ""
        ).strip()

    contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    phone = _digitos_telefone(
        payload.get("senderNumber")
        or contact.get("number")
        or contact.get("phone")
        or payload.get("number")
        or payload.get("phone")
    )

    # userId preenchido = mensagem enviada pelo WhatsAtende/API (fromMe)
    user_id = payload.get("userId")
    from_me = bool(
        user_id not in (None, "", 0, "0")
        or payload.get("fromMe")
        or payload.get("isFromMe")
        or message_obj.get("fromMe")
    )

    mid = (
        payload.get("id")
        or payload.get("messageId")
        or message_obj.get("id")
        or message_obj.get("messageId")
    )
    msg_type = str(payload.get("type") or message_obj.get("type") or "text").lower()

    canonico: Dict[str, Any] = {
        "phone": phone,
        "from": phone,
        "fromMe": from_me,
        "isFromMe": from_me,
        "isGroup": bool(payload.get("isGroup") or "@g.us" in str(phone)),
        "messageId": mid,
        "type": "ReceivedCallback",
        "message": {"text": texto, "body": texto},
        "text": {"message": texto, "text": texto},
        "ticketId": payload.get("ticketId"),
        "queueId": payload.get("queueId"),
        "whatsatendeUserId": user_id,
        "whatsatendeTicketStatus": payload.get("status"),
        "whatsatendeMessageType": msg_type,
        "_whatsatende_raw": payload,
    }

    media_url = (
        payload.get("mediaUrl")
        or message_obj.get("mediaUrl")
        or message_obj.get("media_url")
        or message_obj.get("url")
    )
    mime = str(
        payload.get("mediaType")
        or message_obj.get("mediaType")
        or message_obj.get("mimetype")
        or ""
    ).lower()
    if media_url:
        if msg_type in ("image", "img", "sticker") or "image" in mime:
            canonico["image"] = {"imageUrl": media_url}
        elif msg_type in ("document", "pdf", "file") or "pdf" in mime or "document" in mime:
            canonico["document"] = {"documentUrl": media_url}
        elif msg_type in ("audio", "ptt") or "audio" in mime:
            canonico["audio"] = {"audioUrl": media_url}
        elif msg_type == "video" or "video" in mime:
            canonico["video"] = {"videoUrl": media_url}
        else:
            # fallback: caption de mídia desconhecida
            canonico["document"] = {"documentUrl": media_url}

    # Resposta de botão/template chega como texto normal no webhook (confirmado suporte).
    # Mantém parsing legado se vier estruturado no futuro.
    btn = (
        message_obj.get("buttonsResponseMessage")
        or payload.get("buttonsResponseMessage")
        or msg_bruto.get("buttonsResponseMessage")
        or msg_bruto.get("templateButtonReplyMessage")
    )
    if isinstance(btn, dict):
        bid = (
            btn.get("buttonId")
            or btn.get("selectedButtonId")
            or btn.get("selectedId")
            or btn.get("id")
            or ""
        )
        btxt = (
            btn.get("message")
            or btn.get("selectedDisplayText")
            or btn.get("selectedButtonText")
            or btn.get("text")
            or ""
        )
        canonico["buttonsResponseMessage"] = {
            "buttonId": str(bid),
            "selectedButtonId": str(bid),
            "message": str(btxt),
            "selectedButtonText": str(btxt),
        }
        if btxt and not texto:
            canonico["message"] = {"text": str(btxt), "body": str(btxt)}
            canonico["text"] = {"message": str(btxt), "text": str(btxt)}

    return canonico


def _extrair_texto_evolution(msg: Dict[str, Any]) -> str:
    if not msg:
        return ""
    if msg.get("conversation"):
        return str(msg["conversation"]).strip()
    ext = msg.get("extendedTextMessage") or {}
    if isinstance(ext, dict) and ext.get("text"):
        return str(ext["text"]).strip()
    for key in ("imageMessage", "videoMessage", "documentMessage"):
        part = msg.get(key)
        if isinstance(part, dict) and part.get("caption"):
            return str(part["caption"]).strip()
    return ""


def _extrair_botao_evolution(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(msg, dict):
        return None
    for key in (
        "buttonsResponseMessage",
        "templateButtonReplyMessage",
        "interactiveResponseMessage",
    ):
        br = msg.get(key)
        if not isinstance(br, dict):
            continue
        bid = (
            br.get("selectedButtonId")
            or br.get("selectedId")
            or br.get("buttonId")
            or br.get("id")
            or ""
        )
        texto = (
            br.get("selectedDisplayText")
            or br.get("selectedButtonText")
            or br.get("displayText")
            or br.get("text")
            or ""
        )
        if bid or texto:
            return {
                "buttonId": str(bid),
                "selectedButtonId": str(bid),
                "message": str(texto),
                "selectedButtonText": str(texto),
            }
    return None


def _jid_para_phone(remote_jid: str, participant: str = "") -> Tuple[str, bool, str]:
    jid = str(remote_jid or "")
    part = str(participant or "")
    is_group = "@g.us" in jid or "-group" in jid
    phone = jid.split("@")[0] if "@" in jid else jid
    if is_group and "@g.us" in jid:
        phone = phone + "-group"
    participant_phone = part.split("@")[0] if part else ""
    return phone, is_group, participant_phone


def _resolver_midia_evolution(
    msg: Dict[str, Any], evolution_data: Dict[str, Any], payload: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Retorna (image_url_or_data_uri, document_url_or_data_uri, mime).
    Usa URL direta se presente; senao baixa base64 via Evolution API.
    """
    image_url = None
    document_url = None
    mime = None

    img = msg.get("imageMessage")
    if isinstance(img, dict):
        mime = img.get("mimetype") or "image/jpeg"
        if img.get("url"):
            image_url = img["url"]
        elif img.get("directPath"):
            image_url = None

    doc = msg.get("documentMessage")
    if isinstance(doc, dict):
        mime = doc.get("mimetype") or "application/pdf"
        if doc.get("url"):
            document_url = doc["url"]

    if image_url or document_url:
        return image_url, document_url, mime

    tem_midia = any(
        isinstance(msg.get(k), dict)
        for k in ("imageMessage", "documentMessage", "videoMessage", "audioMessage")
    )
    if not tem_midia:
        return None, None, None

    try:
        from crm_app.services.whatsapp.evolution_provider import EvolutionProvider

        provider = EvolutionProvider()
        envelope = {
            "key": evolution_data.get("key") or {},
            "message": msg,
            "messageTimestamp": evolution_data.get("messageTimestamp"),
        }
        b64 = provider.baixar_midia_base64(envelope)
        if not b64:
            return None, None, mime
        if isinstance(msg.get("imageMessage"), dict):
            mt = mime or "image/jpeg"
            return f"data:{mt};base64,{b64}", None, mt
        if isinstance(msg.get("documentMessage"), dict):
            mt = mime or "application/pdf"
            return None, f"data:{mt};base64,{b64}", mt
    except Exception as exc:
        logger.warning("[WebhookNormalizer] Falha ao baixar midia Evolution: %s", exc)

    return None, None, mime


def _normalizar_evolution(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload

    key = data.get("key") or {}
    msg = data.get("message") or {}
    if not isinstance(msg, dict):
        msg = {}

    remote_jid = key.get("remoteJid") or ""
    participant = key.get("participant") or data.get("participant") or ""
    phone, is_group, participant_phone = _jid_para_phone(remote_jid, participant)

    texto = _extrair_texto_evolution(msg)
    botao = _extrair_botao_evolution(msg)
    image_url, document_url, _mime = _resolver_midia_evolution(msg, data, payload)

    canonico: Dict[str, Any] = {
        "phone": phone,
        "from": phone,
        "fromMe": bool(key.get("fromMe")),
        "isFromMe": bool(key.get("fromMe")),
        "isGroup": is_group,
        "messageId": key.get("id"),
        "type": "message",
        "message": {"text": texto, "body": texto},
        "text": {"message": texto, "text": texto},
    }

    if participant_phone:
        canonico["participantPhone"] = participant_phone
        if isinstance(canonico.get("text"), dict):
            canonico["text"]["participant"] = participant_phone

    if botao:
        canonico["buttonsResponseMessage"] = botao

    ref = None
    ext_ctx = (msg.get("extendedTextMessage") or {}).get("contextInfo")
    if isinstance(ext_ctx, dict):
        ref = ext_ctx
    if not ref:
        for val in msg.values():
            if isinstance(val, dict) and isinstance(val.get("contextInfo"), dict):
                ref = val["contextInfo"]
                break
    if isinstance(ref, dict):
        ref_id = ref.get("stanzaId") or ref.get("quotedMessageId")
        if ref_id:
            canonico["referenceMessageId"] = ref_id

    if image_url:
        if image_url.startswith("data:"):
            canonico["image"] = {"image": image_url}
        else:
            canonico["image"] = {"imageUrl": image_url}

    if document_url:
        if document_url.startswith("data:"):
            canonico["document"] = {"document": document_url}
        else:
            canonico["document"] = {"documentUrl": document_url}

    canonico["_evolution_raw"] = payload
    return canonico
