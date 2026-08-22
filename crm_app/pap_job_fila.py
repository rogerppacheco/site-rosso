"""
Fila de jobs PAP em PostgreSQL — isola Playwright do serviço web sem Redis.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class PapJobFila(models.Model):
    STATUS_PENDENTE = "pendente"
    STATUS_PROCESSANDO = "processando"
    STATUS_CONCLUIDO = "concluido"
    STATUS_ERRO = "erro"

    STATUS_CHOICES = [
        (STATUS_PENDENTE, "Pendente"),
        (STATUS_PROCESSANDO, "Processando"),
        (STATUS_CONCLUIDO, "Concluído"),
        (STATUS_ERRO, "Erro"),
    ]

    tipo = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDENTE,
        db_index=True,
    )
    prioridade = models.SmallIntegerField(default=5, db_index=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    max_tentativas = models.PositiveSmallIntegerField(default=2)
    erro = models.TextField(blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    telefone = models.CharField(max_length=32, blank=True, default="", db_index=True)

    class Meta:
        db_table = "crm_pap_job_fila"
        ordering = ["prioridade", "criado_em"]
        indexes = [
            models.Index(fields=["status", "prioridade", "criado_em"]),
        ]

    def __str__(self) -> str:
        return f"PapJobFila({self.id}, {self.tipo}, {self.status})"


def enfileirar_job_pap(
    tipo: str,
    payload: dict[str, Any],
    *,
    telefone: str = "",
    prioridade: int = 5,
) -> PapJobFila:
    job = PapJobFila.objects.create(
        tipo=tipo,
        payload=payload,
        telefone=telefone or "",
        prioridade=prioridade,
    )
    logger.info("[PAP_FILA] Job %s enfileirado tipo=%s telefone=%s", job.id, tipo, telefone)
    return job


def reivindicar_proximo_job() -> PapJobFila | None:
    """Claim atômico do próximo job pendente (SELECT FOR UPDATE SKIP LOCKED)."""
    with transaction.atomic():
        job = (
            PapJobFila.objects.select_for_update(skip_locked=True)
            .filter(status=PapJobFila.STATUS_PENDENTE)
            .order_by("prioridade", "criado_em")
            .first()
        )
        if not job:
            return None
        job.status = PapJobFila.STATUS_PROCESSANDO
        job.iniciado_em = timezone.now()
        job.tentativas = (job.tentativas or 0) + 1
        job.save(update_fields=["status", "iniciado_em", "tentativas"])
        return job


def _stale_processando_minutos() -> int:
    return int(getattr(settings, "PAP_JOB_STALE_PROCESSANDO_MINUTES", 12))


def _stale_pendente_minutos() -> int:
    """Pendentes acima disso já passaram do timeout do WhatsApp (STATUS ~3 min)."""
    return int(getattr(settings, "PAP_JOB_STALE_PENDENTE_MINUTES", 10))


def recuperar_jobs_pap_travados() -> dict[str, int]:
    """
    Recupera a fila quando o worker morre/trava no Playwright.

    - processando antigo: recola como pendente (se ainda há tentativas) ou erro
    - pendente antigo: marca erro (usuário já recebeu timeout no WhatsApp; reprocessar spamaria)
    """
    agora = timezone.now()
    limite_proc = agora - timedelta(minutes=_stale_processando_minutos())
    limite_pend = agora - timedelta(minutes=_stale_pendente_minutos())
    stats = {"processando_requeued": 0, "processando_erro": 0, "pendente_expirado": 0}

    travados = list(
        PapJobFila.objects.filter(
            status=PapJobFila.STATUS_PROCESSANDO,
            iniciado_em__lt=limite_proc,
        ).order_by("iniciado_em")[:100]
    )
    for job in travados:
        idade_criado_min = (agora - job.criado_em).total_seconds() / 60.0 if job.criado_em else 0
        msg = (
            f"Job abandonado: travado em processando desde {job.iniciado_em} "
            f"(>{_stale_processando_minutos()} min)."
        )
        # Jobs muito antigos: não reprocessar (WhatsApp já deu timeout ao usuário).
        if idade_criado_min >= _stale_pendente_minutos() or (job.tentativas or 0) >= (job.max_tentativas or 2):
            job.status = PapJobFila.STATUS_ERRO
            job.concluido_em = agora
            job.erro = msg[:4000]
            job.save(update_fields=["status", "concluido_em", "erro"])
            stats["processando_erro"] += 1
            logger.warning(
                "[PAP_FILA] Job %s marcado erro (processando stale).",
                job.id,
            )
        else:
            job.status = PapJobFila.STATUS_PENDENTE
            job.iniciado_em = None
            job.erro = msg[:4000]
            job.save(update_fields=["status", "iniciado_em", "erro"])
            stats["processando_requeued"] += 1
            logger.warning("[PAP_FILA] Job %s recolocável (processando stale).", job.id)

    expirados = list(
        PapJobFila.objects.filter(
            status=PapJobFila.STATUS_PENDENTE,
            criado_em__lt=limite_pend,
        ).order_by("criado_em")[:500]
    )
    if expirados:
        ids = [j.id for j in expirados]
        msg = (
            f"Job expirado: ficou pendente >{_stale_pendente_minutos()} min "
            "(usuário já saiu do fluxo WhatsApp)."
        )
        n = PapJobFila.objects.filter(
            id__in=ids, status=PapJobFila.STATUS_PENDENTE
        ).update(
            status=PapJobFila.STATUS_ERRO,
            concluido_em=agora,
            erro=msg[:4000],
        )
        stats["pendente_expirado"] = n
        if n:
            logger.warning("[PAP_FILA] %s job(s) pendente(s) expirados.", n)

    return stats
