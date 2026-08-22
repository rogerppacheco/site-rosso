"""
Worker dedicado para webhooks WhatsApp (fila PostgreSQL).

Uso: python manage.py run_webhook_worker
Railway: serviço site-record-webhook com WHATSAPP_WORKER_MODE=true
"""
from __future__ import annotations

import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from crm_app.services.webhook_job_processor import processar_job
from crm_app.whatsapp_webhook_fila import reivindicar_proximo_webhook


class Command(BaseCommand):
    help = "Processa fila de webhooks WhatsApp em processo dedicado."

    def handle(self, *args, **options) -> None:
        intervalo = float(getattr(settings, "WHATSAPP_WORKER_POLL_SECONDS", 1.0))
        self._running = True

        def _shutdown(signum=None, frame=None) -> None:
            self.stdout.write(
                self.style.WARNING(f"[WEBHOOK_WORKER] Sinal {signum} — encerrando...")
            )
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        self.stdout.write(
            self.style.SUCCESS(
                f"[WEBHOOK_WORKER] Iniciado (poll={intervalo}s). "
                f"WHATSAPP_WORKER_MODE={getattr(settings, 'WHATSAPP_WORKER_MODE', False)}"
            )
        )

        while self._running:
            job = reivindicar_proximo_webhook()
            if job:
                processar_job(job)
                continue
            time.sleep(intervalo)

        self.stdout.write(self.style.SUCCESS("[WEBHOOK_WORKER] Encerrado."))
