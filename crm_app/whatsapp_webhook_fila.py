"""
Fila de webhooks WhatsApp em PostgreSQL — isola processamento pesado do serviço web.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class WhatsappWebhookFila(models.Model):
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

    payload = models.JSONField(default=dict)
    base_url = models.CharField(max_length=256, blank=True, default="")
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
        db_table = "crm_whatsapp_webhook_fila"
        ordering = ["prioridade", "criado_em"]
        indexes = [
            models.Index(fields=["status", "prioridade", "criado_em"]),
        ]

    def __str__(self) -> str:
        return f"WhatsappWebhookFila({self.id}, {self.telefone}, {self.status})"


def _extrair_telefone(payload: dict[str, Any]) -> str:
    phone = (
        payload.get("phone")
        or payload.get("from")
        or payload.get("phoneNumber")
        or ""
    )
    return str(phone)[:32]


def enfileirar_webhook(
    payload: dict[str, Any],
    *,
    base_url: str = "",
    prioridade: int = 5,
) -> WhatsappWebhookFila:
    job = WhatsappWebhookFila.objects.create(
        payload=payload,
        base_url=(base_url or "").rstrip("/"),
        telefone=_extrair_telefone(payload),
        prioridade=prioridade,
    )
    logger.info(
        "[WEBHOOK_FILA] Job %s enfileirado telefone=%s",
        job.id,
        job.telefone,
    )
    return job


def reivindicar_proximo_webhook() -> WhatsappWebhookFila | None:
    """Claim atômico do próximo webhook pendente (SELECT FOR UPDATE SKIP LOCKED)."""
    with transaction.atomic():
        job = (
            WhatsappWebhookFila.objects.select_for_update(skip_locked=True)
            .filter(status=WhatsappWebhookFila.STATUS_PENDENTE)
            .order_by("prioridade", "criado_em")
            .first()
        )
        if not job:
            return None
        job.status = WhatsappWebhookFila.STATUS_PROCESSANDO
        job.iniciado_em = timezone.now()
        job.tentativas = (job.tentativas or 0) + 1
        job.save(update_fields=["status", "iniciado_em", "tentativas"])
        return job
