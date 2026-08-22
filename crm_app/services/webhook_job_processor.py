"""
Processamento de jobs da fila de webhooks WhatsApp (serviço dedicado).
"""
from __future__ import annotations

import logging
import traceback

from django.utils import timezone

from crm_app.services.webhook_async_dispatcher import WebhookRequestContext
from crm_app.whatsapp_webhook_fila import WhatsappWebhookFila

logger = logging.getLogger(__name__)


def processar_job(job: WhatsappWebhookFila) -> bool:
    """Executa um webhook enfileirado e atualiza status. Retorna True se concluído."""
    import django.db

    django.db.close_old_connections()
    try:
        logger.info("[WEBHOOK_WORKER] Processando job %s telefone=%s", job.id, job.telefone)
        from crm_app.whatsapp_webhook_handler import processar_webhook_whatsapp

        ctx = WebhookRequestContext()
        if job.base_url:
            ctx._base = job.base_url.rstrip("/")

        resultado = processar_webhook_whatsapp(job.payload or {}, request=ctx)
        status = resultado.get("status", "?") if isinstance(resultado, dict) else "?"
        logger.info("[WEBHOOK_WORKER] Job %s concluído status=%s", job.id, status)

        job.status = WhatsappWebhookFila.STATUS_CONCLUIDO
        job.concluido_em = timezone.now()
        job.erro = ""
        job.save(update_fields=["status", "concluido_em", "erro"])
        return True
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[WEBHOOK_WORKER] Erro job %s: %s", job.id, exc)
        if job.tentativas < job.max_tentativas:
            job.status = WhatsappWebhookFila.STATUS_PENDENTE
            job.erro = f"{exc}\n{tb}"[:4000]
            job.save(update_fields=["status", "erro"])
            return False
        job.status = WhatsappWebhookFila.STATUS_ERRO
        job.concluido_em = timezone.now()
        job.erro = f"{exc}\n{tb}"[:4000]
        job.save(update_fields=["status", "concluido_em", "erro"])
        return False
    finally:
        django.db.close_old_connections()
