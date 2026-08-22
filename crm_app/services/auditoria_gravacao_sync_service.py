"""
Sincronização de gravações de auditoria para Cloudflare R2.

Cobre Sonax (pega_gravacao), URL do provedor (Zenvia/webhook) e migração de links OneDrive.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.db.models import Q, QuerySet

from crm_app.models import AuditoriaLigacao

logger = logging.getLogger(__name__)


def link_gravacao_ja_no_r2(link: Optional[str]) -> bool:
    """Retorna True se o link já aponta para o bucket R2."""
    lower = (link or "").strip().lower()
    return "r2.dev" in lower or "cloudflarestorage.com" in lower


def ligacao_precisa_arquivar_r2(ligacao: AuditoriaLigacao) -> bool:
    """Ligação ainda sem backup no R2 (vazio, OneDrive ou outro host)."""
    return not link_gravacao_ja_no_r2(ligacao.link_gravacao_onedrive)


def queryset_ligacoes_pendentes_r2() -> QuerySet[AuditoriaLigacao]:
    """Ligações cuja gravação ainda não está no R2."""
    return (
        AuditoriaLigacao.objects.filter(
            Q(link_gravacao_onedrive__isnull=True)
            | Q(link_gravacao_onedrive="")
            | Q(link_gravacao_onedrive__icontains="sharepoint")
            | Q(link_gravacao_onedrive__icontains="onedrive")
        )
        .exclude(link_gravacao_onedrive__icontains="r2.dev")
        .order_by("criado_em")
    )


def sincronizar_gravacao_ligacao_r2(ligacao: AuditoriaLigacao) -> tuple[str, str]:
    """
    Tenta arquivar a gravação no R2.

    Returns:
        (status, detalhe) — status em ok, skip, erro.
    """
    from crm_app.auditoria_ligacoes_api import (
        _sync_recording_to_r2,
        _try_sonax_download_and_archive,
        _upload_bytes_to_r2,
    )

    if not ligacao_precisa_arquivar_r2(ligacao):
        return "skip", "já no R2"

    link_backup = (ligacao.link_gravacao_onedrive or "").strip()
    link_provedor = (ligacao.link_gravacao_provedor or "").strip()

    # 1) Baixar da URL do provedor (Zenvia / webhook Sonax)
    if link_provedor:
        try:
            backup_anterior = ligacao.link_gravacao_onedrive
            ligacao.link_gravacao_onedrive = None
            _sync_recording_to_r2(ligacao)
            ligacao.refresh_from_db()
            if link_gravacao_ja_no_r2(ligacao.link_gravacao_onedrive):
                return "ok", "provedor"
            ligacao.link_gravacao_onedrive = backup_anterior
            ligacao.save(update_fields=["link_gravacao_onedrive", "atualizado_em"])
        except Exception as exc:
            logger.warning(
                "Falha ao arquivar via provedor (ligacao_id=%s): %s",
                ligacao.id,
                exc,
            )

    # 2) Sonax pega_gravacao
    if str(ligacao.provedor or "").upper() == "SONAX":
        try:
            backup_anterior = ligacao.link_gravacao_onedrive
            if link_backup and not link_gravacao_ja_no_r2(link_backup):
                ligacao.link_gravacao_onedrive = None
                ligacao.save(update_fields=["link_gravacao_onedrive", "atualizado_em"])
            _try_sonax_download_and_archive(ligacao)
            ligacao.refresh_from_db()
            if link_gravacao_ja_no_r2(ligacao.link_gravacao_onedrive):
                return "ok", "sonax"
            if backup_anterior and not link_gravacao_ja_no_r2(ligacao.link_gravacao_onedrive):
                ligacao.link_gravacao_onedrive = backup_anterior
                ligacao.save(update_fields=["link_gravacao_onedrive", "atualizado_em"])
        except Exception as exc:
            logger.warning(
                "Falha ao arquivar via Sonax (ligacao_id=%s): %s",
                ligacao.id,
                exc,
            )

    # 3) Migrar link OneDrive/SharePoint existente
    if link_backup and not link_gravacao_ja_no_r2(link_backup):
        try:
            response = requests.get(link_backup, timeout=90)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            extension = ".mp3"
            if "wav" in content_type:
                extension = ".wav"
            elif "ogg" in content_type:
                extension = ".ogg"
            elif "mp4" in content_type:
                extension = ".mp4"

            content = response.content
            if content[:2] == b"PK":
                from crm_app.auditoria_ligacoes_api import unpack_recording_zip
                from django.conf import settings

                prefer_mp3 = bool(getattr(settings, "SONAX_RECORDING_PREFER_MP3", True))
                content, extension = unpack_recording_zip(content, prefer_mp3=prefer_mp3)

            _upload_bytes_to_r2(ligacao, content, extension)
            ligacao.refresh_from_db()
            if link_gravacao_ja_no_r2(ligacao.link_gravacao_onedrive):
                return "ok", "onedrive"
        except Exception as exc:
            logger.warning(
                "Falha ao migrar OneDrive (ligacao_id=%s): %s",
                ligacao.id,
                exc,
            )

    return "erro", "sem fonte disponível"


def sincronizar_todas_gravacoes_r2(
    *,
    lote: int = 50,
    max_lotes: Optional[int] = None,
    pausa_segundos: float = 0.5,
) -> dict[str, int]:
    """
    Processa lotes até esgotar pendências ou atingir max_lotes.

    Returns:
        Contadores acumulados ok, skip, erro, lotes.
    """
    import time

    totais = {"ok": 0, "skip": 0, "erro": 0, "lotes": 0, "processadas": 0}
    lote_atual = 0
    ids_erro_sessao: set[int] = set()

    while True:
        if max_lotes is not None and lote_atual >= max_lotes:
            break

        qs = queryset_ligacoes_pendentes_r2()
        if ids_erro_sessao:
            qs = qs.exclude(id__in=ids_erro_sessao)
        pendentes = list(qs[:lote])
        if not pendentes:
            break

        lote_atual += 1
        totais["lotes"] = lote_atual

        for ligacao in pendentes:
            status, _detalhe = sincronizar_gravacao_ligacao_r2(ligacao)
            totais[status] = totais.get(status, 0) + 1
            totais["processadas"] += 1
            if status == "erro":
                ids_erro_sessao.add(ligacao.id)
            if pausa_segundos > 0:
                time.sleep(pausa_segundos)

    totais["restantes"] = queryset_ligacoes_pendentes_r2().count()
    totais["erros_unicos_sessao"] = len(ids_erro_sessao)
    return totais
