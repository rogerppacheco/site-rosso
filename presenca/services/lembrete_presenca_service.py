"""
Lembretes automáticos de presença para supervisores (WhatsApp 10h/11h) e
aplicação de falta automática às 12h quando o lançamento não foi concluído.
"""
from __future__ import annotations

import base64
import logging
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from presenca.models import ConfirmacaoPresencaDia, DiaNaoUtil, LogLembretePresencaSupervisor, MotivoAusencia, Presenca
from presenca.services.presenca_service import registrar_presenca
from usuarios.models import Usuario

logger = logging.getLogger(__name__)

SLOT_10H = "10h"
SLOT_11H = "11h"
SLOT_12H_FALTA = "12h_falta"

_CAPTION_10H = (
    "⚠️ *ALERTA SUPERVISOR*\n\n"
    "Você ainda não concluiu os lançamentos de presença de hoje.\n\n"
    "Acesse {url} e finalize *antes das 12h*."
)

_CAPTION_11H = (
    "🚨 *ALERTA SUPERVISOR — URGENTE*\n\n"
    "Se os lançamentos de presença *não forem concluídos até 12h*, "
    "a *FALTA será aplicada automaticamente para TODOS* da sua equipe!\n\n"
    "Acesse agora: {url}"
)


def _url_presenca() -> str:
    return getattr(settings, "PRESENCA_URL_SITE", "https://www.recordpap.com.br/presenca/")


def _imagem_alerta_b64() -> str:
    """Carrega a imagem estática ALERTA SUPERVISOR em base64 (sem prefixo data:)."""
    rel = getattr(
        settings,
        "PRESENCA_IMAGEM_ALERTA_SUPERVISOR",
        "presenca/assets/alerta_supervisor.png",
    )
    caminho = Path(settings.BASE_DIR) / rel
    if not caminho.is_file():
        raise FileNotFoundError(f"Imagem de alerta não encontrada: {caminho}")
    return base64.b64encode(caminho.read_bytes()).decode("utf-8")


def _eh_dia_util(data_dia: date) -> bool:
    if data_dia.weekday() >= 5:
        return False
    return not DiaNaoUtil.objects.filter(data=data_dia).exists()


def _equipe_do_supervisor(supervisor: Usuario) -> QuerySet[Usuario]:
    if getattr(supervisor, "vendedor_solo", False):
        return Usuario.objects.filter(
            id=supervisor.id,
            is_active=True,
            participa_controle_presenca=True,
        )
    return supervisor.liderados.filter(
        is_active=True,
        participa_controle_presenca=True,
    ).order_by("first_name")


def listar_supervisores_com_equipe() -> QuerySet[Usuario]:
    """Supervisores ativos com equipe no controle de presença e WhatsApp cadastrado."""
    com_liderados = Usuario.objects.filter(
        is_active=True,
        tel_whatsapp__isnull=False,
    ).exclude(tel_whatsapp="").filter(
        liderados__is_active=True,
        liderados__participa_controle_presenca=True,
    ).distinct()

    solo = Usuario.objects.filter(
        is_active=True,
        vendedor_solo=True,
        participa_controle_presenca=True,
        tel_whatsapp__isnull=False,
    ).exclude(tel_whatsapp="").distinct()

    return (com_liderados | solo).order_by("username")


def supervisor_pendente(supervisor: Usuario, data_dia: date) -> bool:
    """
    Pendente = selfie do dia não confirmada OU algum membro da equipe sem registro de presença.
    """
    equipe = list(_equipe_do_supervisor(supervisor))
    if not equipe:
        return False

    if not ConfirmacaoPresencaDia.objects.filter(
        supervisor=supervisor,
        data=data_dia,
    ).exists():
        return True

    ids_equipe = [u.id for u in equipe]
    registrados = Presenca.objects.filter(
        data=data_dia,
        colaborador_id__in=ids_equipe,
    ).count()
    return registrados < len(ids_equipe)


def _normalizar_tel_whatsapp(usuario: Usuario) -> str:
    return (
        (usuario.tel_whatsapp or "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


def _ja_enviou(data_dia: date, slot: str, supervisor_id: int) -> bool:
    return LogLembretePresencaSupervisor.objects.filter(
        data=data_dia,
        slot=slot,
        supervisor_id=supervisor_id,
    ).exists()


def _registrar_envio(
    data_dia: date,
    slot: str,
    supervisor: Usuario,
    sucesso: bool,
    detalhe: str = "",
) -> None:
    LogLembretePresencaSupervisor.objects.get_or_create(
        data=data_dia,
        slot=slot,
        supervisor=supervisor,
        defaults={
            "sucesso": sucesso,
            "detalhe": (detalhe or "")[:500],
        },
    )


def _obter_motivo_falta_automatica() -> MotivoAusencia:
    nome = getattr(
        settings,
        "PRESENCA_MOTIVO_FALTA_AUTOMATICA",
        "Falta automática (supervisor)",
    )
    motivo, _ = MotivoAusencia.objects.get_or_create(
        motivo=nome,
        defaults={"gera_desconto": True},
    )
    if not motivo.gera_desconto:
        motivo.gera_desconto = True
        motivo.save(update_fields=["gera_desconto"])
    return motivo


def enviar_lembrete_supervisores(slot: str) -> dict[str, Any]:
    """
    Envia lembrete por WhatsApp (imagem + legenda) para supervisores pendentes.
    slot: '10h' ou '11h'
    """
    if not getattr(settings, "PRESENCA_LEMBRETES_ATIVOS", True):
        return {"ativo": False, "enviados": 0}

    agora = timezone.localtime(timezone.now())
    data_dia = agora.date()

    if not _eh_dia_util(data_dia):
        logger.info("[Presença lembrete %s] Dia não útil (%s) — ignorado", slot, data_dia)
        return {"dia_util": False, "enviados": 0}

    if slot == SLOT_10H:
        caption_tpl = _CAPTION_10H
    elif slot == SLOT_11H:
        caption_tpl = _CAPTION_11H
    else:
        raise ValueError(f"Slot de lembrete inválido: {slot}")

    caption = caption_tpl.format(url=_url_presenca())
    img_b64 = _imagem_alerta_b64()

    from crm_app.whatsapp_service import WhatsAppService

    svc = WhatsAppService()
    enviados = 0
    falhas = 0
    ignorados = 0

    for supervisor in listar_supervisores_com_equipe():
        if not supervisor_pendente(supervisor, data_dia):
            ignorados += 1
            continue
        if _ja_enviou(data_dia, slot, supervisor.id):
            ignorados += 1
            continue

        tel = _normalizar_tel_whatsapp(supervisor)
        if not tel:
            _registrar_envio(data_dia, slot, supervisor, False, "Sem tel_whatsapp")
            falhas += 1
            continue

        try:
            resultado = svc.enviar_imagem_b64(tel, img_b64, caption=caption)
            if resultado:
                enviados += 1
                _registrar_envio(data_dia, slot, supervisor, True)
                logger.info(
                    "[Presença lembrete %s] Enviado para %s",
                    slot,
                    supervisor.username,
                )
            else:
                falhas += 1
                _registrar_envio(data_dia, slot, supervisor, False, "Z-API não confirmou")
        except Exception as exc:
            falhas += 1
            _registrar_envio(data_dia, slot, supervisor, False, str(exc)[:500])
            logger.warning(
                "[Presença lembrete %s] Falha %s: %s",
                slot,
                supervisor.username,
                exc,
            )

    resumo = {
        "slot": slot,
        "data": data_dia.isoformat(),
        "enviados": enviados,
        "falhas": falhas,
        "ignorados": ignorados,
    }
    logger.info("[Presença lembrete %s] Resumo: %s", slot, resumo)
    return resumo


def aplicar_faltas_automaticas_12h() -> dict[str, Any]:
    """
    Às 12h, para supervisores ainda pendentes, aplica falta a todos da equipe.
    """
    if not getattr(settings, "PRESENCA_FALTA_AUTOMATICA_12H_ATIVA", True):
        return {"ativo": False, "supervisores": 0}

    agora = timezone.localtime(timezone.now())
    data_dia = agora.date()

    if not _eh_dia_util(data_dia):
        return {"dia_util": False, "supervisores": 0}

    motivo = _obter_motivo_falta_automatica()
    observacao = "Falta automática — lançamento de presença não concluído até 12h."
    supervisores_processados = 0
    colaboradores_afetados = 0

    for supervisor in listar_supervisores_com_equipe():
        if not supervisor_pendente(supervisor, data_dia):
            continue
        if _ja_enviou(data_dia, SLOT_12H_FALTA, supervisor.id):
            continue

        equipe = list(_equipe_do_supervisor(supervisor))
        afetados_slot = 0
        for colaborador in equipe:
            try:
                registrar_presenca(
                    colaborador_id=colaborador.id,
                    data_registro=data_dia,
                    status=False,
                    motivo_id=motivo.id,
                    observacao=observacao,
                    usuario=None,
                )
                afetados_slot += 1
            except Exception as exc:
                logger.warning(
                    "[Presença 12h] Falha ao registrar falta %s (supervisor %s): %s",
                    colaborador.username,
                    supervisor.username,
                    exc,
                )

        _registrar_envio(
            data_dia,
            SLOT_12H_FALTA,
            supervisor,
            afetados_slot > 0,
            f"{afetados_slot} colaborador(es)",
        )
        supervisores_processados += 1
        colaboradores_afetados += afetados_slot
        logger.info(
            "[Presença 12h] Falta automática: supervisor=%s, colaboradores=%s",
            supervisor.username,
            afetados_slot,
        )

    resumo = {
        "data": data_dia.isoformat(),
        "supervisores": supervisores_processados,
        "colaboradores": colaboradores_afetados,
    }
    logger.info("[Presença 12h] Resumo: %s", resumo)
    return resumo
