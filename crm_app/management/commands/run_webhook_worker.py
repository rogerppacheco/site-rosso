"""
Worker dedicado para webhooks WhatsApp (fila PostgreSQL).

Uso: python manage.py run_webhook_worker
Railway: serviço nova-velox-webhook com WHATSAPP_WORKER_MODE=true
"""
from __future__ import annotations

import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.utils import InterfaceError, OperationalError

from crm_app.services.webhook_job_processor import processar_job
from crm_app.services.whatsapp.preflight import checar_config_outbound
from crm_app.whatsapp_webhook_fila import reivindicar_proximo_webhook


class Command(BaseCommand):
    help = "Processa fila de webhooks WhatsApp em processo dedicado."

    def handle(self, *args, **options) -> None:
        intervalo = float(getattr(settings, "WHATSAPP_WORKER_POLL_SECONDS", 1.0))
        self._running = True
        falhas_db_seguidas = 0

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

        faltando = checar_config_outbound("WEBHOOK_WORKER")
        if faltando:
            self.stderr.write(
                self.style.ERROR(
                    f"[WEBHOOK_WORKER] Sem credenciais de envio: {', '.join(faltando)}"
                )
            )

        while self._running:
            close_old_connections()
            try:
                job = reivindicar_proximo_webhook()
                falhas_db_seguidas = 0
            except (OperationalError, InterfaceError) as exc:
                falhas_db_seguidas += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"[WEBHOOK_WORKER] Falha de conexão DB ({falhas_db_seguidas}): {exc}"
                    )
                )
                close_old_connections()
                time.sleep(min(30.0, intervalo * falhas_db_seguidas))
                continue

            if job:
                processar_job(job)
                continue
            time.sleep(intervalo)

        self.stdout.write(self.style.SUCCESS("[WEBHOOK_WORKER] Encerrado."))
