"""
Correlaciona aceite do envio (wamid) com status posterior da Meta/WhatsAtende.

HTTP 200 no POST /messages = ACEITO, não entrega. Falhas como 131048 (spam)
chegam depois no webhook de status.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional, Tuple

from django.utils import timezone

logger = logging.getLogger(__name__)

STATUS_ACEITO = "ACEITO"
STATUS_ENVIADO = "ENVIADO"
STATUS_ENTREGUE = "ENTREGUE"
STATUS_LIDO = "LIDO"
STATUS_FALHOU = "FALHOU"

_RANK = {
    STATUS_ACEITO: 1,
    STATUS_ENVIADO: 2,
    STATUS_ENTREGUE: 3,
    STATUS_LIDO: 4,
    STATUS_FALHOU: 5,
}

CODIGOS_META = {
    "130429": "Rate limit da Cloud API",
    "131021": "Destinatário não pode receber a mensagem",
    "131026": "Número não está no WhatsApp",
    "131031": "Conta do remetente bloqueada",
    "131047": "Janela de 24h expirada (reengajamento)",
    "131048": "Limite de taxa de spam atingido",
    "131049": "Mensagem não entregue para manter qualidade da conta",
    "131051": "Tipo de mensagem não suportado",
    "131053": "Falha ao baixar mídia",
    "132000": "Parâmetros do template inválidos",
    "132001": "Template não existe",
    "132005": "Template pausado",
    "132007": "Template desabilitado",
    "132012": "Parâmetro do template incompatível",
    "132015": "Template reprovado em experimento",
    "132016": "Template com formatação inválida",
    "133010": "WABA desconectada do telefone",
}


def extrair_message_id_resposta(resp: Any) -> str:
    """Extrai wamid/messageId da resposta do POST de envio."""
    if not isinstance(resp, dict):
        return ""
    for key in ("messageId", "message_id", "id", "wamid", "zaapId"):
        val = resp.get(key)
        if isinstance(val, dict) and val.get("id"):
            s = str(val["id"]).strip()
            if s:
                return s[:191]
        if val and not isinstance(val, (dict, list)):
            s = str(val).strip()
            if s:
                return s[:191]
    for nest in ("data", "message", "ticket", "result"):
        nested = resp.get(nest)
        if isinstance(nested, dict):
            mid = extrair_message_id_resposta(nested)
            if mid:
                return mid
    return ""


def extrair_erro_meta(payload: Any) -> Tuple[str, str]:
    """Retorna (codigo, mensagem) de payloads Meta / WhatsAtende / send."""
    if not payload:
        return "", ""
    if isinstance(payload, str):
        return "", payload.strip()[:2000]
    if not isinstance(payload, dict):
        return "", str(payload)[:2000]

    code = _primeiro_codigo(
        payload.get("errorCode"),
        payload.get("error_code"),
        payload.get("code"),
        payload.get("statusCode"),
    )
    msg = ""
    errors = payload.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if not isinstance(item, dict):
                continue
            code = code or _primeiro_codigo(item.get("code"), item.get("error_code"))
            details = ""
            err_data = item.get("error_data")
            if isinstance(err_data, dict):
                details = str(err_data.get("details") or "").strip()
            msg = (
                details
                or str(item.get("message") or "").strip()
                or str(item.get("title") or "").strip()
                or msg
            )
            if code:
                break

    err_obj = payload.get("error")
    if isinstance(err_obj, dict):
        code = code or _primeiro_codigo(err_obj.get("code"), err_obj.get("error_code"))
        msg = msg or str(
            err_obj.get("message") or err_obj.get("title") or err_obj.get("error") or ""
        ).strip()
    elif err_obj:
        msg = msg or str(err_obj).strip()

    if not msg:
        msg = str(payload.get("message") or payload.get("title") or "").strip()

    if code and code in ("200", "201"):
        code = ""
    if code and not msg:
        msg = CODIGOS_META.get(code, "")
    if code and msg and code not in msg:
        rotulo = CODIGOS_META.get(code)
        if rotulo and rotulo not in msg:
            msg = f"{rotulo}. {msg}"
    return code[:32], (msg or "")[:2000]


def mapear_status_entrega(
    *,
    ok: Optional[bool],
    wa_status: str = "",
    error: str = "",
    error_code: str = "",
) -> str:
    if error or error_code or ok is False:
        return STATUS_FALHOU
    s = (wa_status or "").strip().upper()
    if s in ("READ", "READ_BY_ME", "PLAYED"):
        return STATUS_LIDO
    if s in ("RECEIVED", "DELIVERED", "DELIVERY_ACK"):
        return STATUS_ENTREGUE
    if s in ("SENT", "SERVER"):
        return STATUS_ENVIADO
    if s in ("FAILED", "ERROR", "FAIL"):
        return STATUS_FALHOU
    return STATUS_ACEITO if ok else STATUS_FALHOU


def persistir_resultado_entrega(
    message_ids: Iterable[str],
    *,
    ok: bool,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    phone: Optional[str] = None,
    source: Optional[str] = None,
    wa_status: str = "",
) -> int:
    """Atualiza HistoricoEnvioQualidade casado pelo message_id. Retorna linhas."""
    ids = [str(i).strip()[:191] for i in message_ids if i and str(i).strip()]
    if not ids:
        return 0

    codigo, msg_erro = extrair_erro_meta(
        {
            "error": error,
            "errorCode": error_code,
            "errors": [{"code": error_code, "message": error}] if error_code else [],
        }
    )
    if not codigo:
        codigo = (error_code or "").strip()[:32]
    if not msg_erro:
        msg_erro = (error or "").strip()[:2000]
    status_novo = mapear_status_entrega(
        ok=ok,
        wa_status=wa_status,
        error=msg_erro if not ok else "",
        error_code=codigo if not ok else "",
    )
    agora = timezone.now()
    atualizados = 0
    try:
        from crm_app.models import HistoricoEnvioQualidade

        qs = HistoricoEnvioQualidade.objects.filter(message_id__in=ids)
        for hist in qs:
            if not _pode_atualizar_status(hist.status_entrega, status_novo):
                continue
            hist.status_entrega = status_novo
            hist.status_atualizado_em = agora
            if codigo:
                hist.erro_codigo = codigo
            if status_novo == STATUS_FALHOU:
                hist.sucesso = False
                if msg_erro:
                    hist.erro = msg_erro
            elif status_novo in (
                STATUS_ENVIADO,
                STATUS_ENTREGUE,
                STATUS_LIDO,
            ):
                hist.sucesso = True
            hist.save(
                update_fields=[
                    "status_entrega",
                    "status_atualizado_em",
                    "erro_codigo",
                    "sucesso",
                    "erro",
                ]
            )
            atualizados += 1
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            return 0
        logger.exception(
            "[StatusEntrega] Falha ao persistir ids=%s status=%s code=%s phone=%s source=%s",
            ids,
            status_novo,
            codigo,
            phone,
            source,
        )
        return 0

    if atualizados:
        logger.info(
            "[StatusEntrega] historico atualizado n=%s ids=%s status=%s code=%s source=%s",
            atualizados,
            ids,
            status_novo,
            codigo,
            source,
        )
    else:
        logger.info(
            "[StatusEntrega] nenhum historico para ids=%s status=%s code=%s source=%s",
            ids,
            status_novo,
            codigo,
            source,
        )
    return atualizados


def processar_webhook_status(payload: Any) -> Optional[Dict[str, Any]]:
    """
    Se o payload for status/falha de entrega, processa cache + histórico.
    Retorna dict de resposta ou None se não for evento de status.
    """
    if not isinstance(payload, dict):
        return None

    from crm_app.whatsapp_webhook_normalizer import extrair_callbacks_status
    from crm_app.services.whatsapp.delivery_tracker import (
        processar_delivery_callback,
        processar_message_status_callback,
    )

    eventos = extrair_callbacks_status(payload)
    if not eventos:
        return None

    ultimo: Optional[Dict[str, Any]] = None
    for ev in eventos:
        tipo = str(ev.get("type") or "").strip().lower()
        codigo, msg_erro = extrair_erro_meta(ev)
        if not codigo:
            codigo = str(ev.get("errorCode") or ev.get("error_code") or "").strip()
        if not msg_erro:
            msg_erro = str(ev.get("error") or "").strip()
        ids = _ids_callback(ev)
        if tipo == "deliverycallback":
            ultimo = processar_delivery_callback(ev)
            persistir_resultado_entrega(
                ids,
                ok=not bool(msg_erro or codigo),
                error=msg_erro or None,
                error_code=codigo or None,
                phone=str(ev.get("phone") or "") or None,
                source="DeliveryCallback",
                wa_status="" if (msg_erro or codigo) else "SENT",
            )
        elif tipo == "messagestatuscallback":
            ultimo = processar_message_status_callback(ev)
            wa_status = str(ev.get("status") or "")
            wa_upper = wa_status.strip().upper()
            if codigo or msg_erro or wa_upper in ("FAILED", "ERROR", "FAIL"):
                persistir_resultado_entrega(
                    ids,
                    ok=False,
                    error=msg_erro or "falha de entrega",
                    error_code=codigo or None,
                    phone=str(ev.get("phone") or "") or None,
                    source=f"MessageStatus:{wa_status}",
                    wa_status=wa_status,
                )
            elif isinstance(ultimo, dict) and ultimo.get("ok") is True:
                persistir_resultado_entrega(
                    ids,
                    ok=True,
                    error=None,
                    error_code=None,
                    phone=str(ev.get("phone") or "") or None,
                    source=f"MessageStatus:{wa_status}",
                    wa_status=wa_status,
                )
        else:
            logger.info("[StatusEntrega] evento ignorado type=%s", tipo)
    return ultimo or {"status": "ok", "mensagem": "Status de entrega processado"}


def _pode_atualizar_status(atual: str, novo: str) -> bool:
    atual_u = (atual or "").strip().upper()
    novo_u = (novo or "").strip().upper()
    if not novo_u:
        return False
    if atual_u == STATUS_FALHOU and novo_u != STATUS_FALHOU:
        return False
    rank_atual = _RANK.get(atual_u, 0)
    rank_novo = _RANK.get(novo_u, 0)
    return rank_novo >= rank_atual


def _primeiro_codigo(*vals: Any) -> str:
    for val in vals:
        if val is None or val == "":
            continue
        s = str(val).strip()
        if not s:
            continue
        digits = "".join(ch for ch in s if ch.isdigit())
        if digits:
            return digits[:32]
        return s[:32]
    return ""


def _ids_callback(data: Dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("messageId", "zaapId", "id"):
        val = data.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s and s not in ids:
            ids.append(s)
    raw_ids = data.get("ids")
    if isinstance(raw_ids, list):
        for val in raw_ids:
            s = str(val).strip() if val is not None else ""
            if s and s not in ids:
                ids.append(s)
    elif raw_ids is not None:
        s = str(raw_ids).strip()
        if s and s not in ids:
            ids.append(s)
    return ids
