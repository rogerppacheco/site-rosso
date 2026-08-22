"""
Worker dedicado para automações Playwright/PAP (fila PostgreSQL).

Uso: python manage.py run_pap_worker
Railway: serviço site-record-pap com PAP_WORKER_MODE=true
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.db_resilience import (
    force_close_db_connections,
    is_db_connection_lost,
    retry_on_db_connection_error,
)
from crm_app.pap_job_fila import PapJobFila, recuperar_jobs_pap_travados, reivindicar_proximo_job
from crm_app.services.pap_job_processor import (
    _notificar_falha_definitiva,
    processar_job,
)

logger = logging.getLogger(__name__)


def _timeout_job_segundos(tipo: str) -> int:
    defaults = {
        "status_online": 240,
        "consulta_pedido": 240,
        "analise_credito": 360,
    }
    base = int(getattr(settings, "PAP_JOB_TIMEOUT_SECONDS", 0) or 0)
    if base > 0:
        return base
    return defaults.get(tipo, 300)


class Command(BaseCommand):
    help = "Processa fila de jobs PAP (Playwright) em processo dedicado."

    def handle(self, *args, **options):
        intervalo = float(getattr(settings, "PAP_WORKER_POLL_SECONDS", 2.0))
        self._running = True
        ciclos_sem_job = 0

        def _shutdown(signum=None, frame=None):
            self.stdout.write(self.style.WARNING(f"[PAP_WORKER] Sinal {signum} — encerrando..."))
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        stats = retry_on_db_connection_error(
            recuperar_jobs_pap_travados,
            label="recuperar_jobs_pap_travados_startup",
        )
        self.stdout.write(self.style.SUCCESS(
            f"[PAP_WORKER] Iniciado (poll={intervalo}s). "
            f"PAP_WORKER_MODE={getattr(settings, 'PAP_WORKER_MODE', False)} "
            f"recuperacao={stats}"
        ))

        while self._running:
            try:
                # Poll longo sem ORM: descarta conexão ociosa antes de tocar no banco.
                force_close_db_connections()

                # A cada ~30s sem job (ou sempre antes de reivindicar periodicamente)
                if ciclos_sem_job == 0 or ciclos_sem_job % 15 == 0:
                    retry_on_db_connection_error(
                        recuperar_jobs_pap_travados,
                        label="recuperar_jobs_pap_travados",
                    )

                job = retry_on_db_connection_error(
                    reivindicar_proximo_job,
                    label="reivindicar_proximo_job",
                )
                if not job:
                    ciclos_sem_job += 1
                    time.sleep(intervalo)
                    continue

                ciclos_sem_job = 0
                timeout_seg = _timeout_job_segundos(job.tipo)
                self.stdout.write(
                    f"[PAP_WORKER] Job {job.id} tipo={job.tipo} timeout={timeout_seg}s"
                )
                travou = self._processar_com_timeout(job, timeout_seg)
                if travou:
                    # Playwright pode ter deixado o processo inconsistente — Railway reinicia.
                    self.stdout.write(self.style.ERROR(
                        f"[PAP_WORKER] Job {job.id} excedeu {timeout_seg}s — "
                        "encerrando worker para limpar Playwright."
                    ))
                    raise SystemExit(1)
            except SystemExit:
                raise
            except Exception as exc:
                # Conexão morta no claim/recuperação não deve derrubar o serviço.
                if is_db_connection_lost(exc):
                    logger.exception(
                        "[PAP_WORKER] Conexão DB perdida no loop — reconectando e seguindo"
                    )
                    force_close_db_connections()
                    time.sleep(max(2.0, intervalo))
                    continue
                logger.exception("[PAP_WORKER] Erro inesperado no loop")
                force_close_db_connections()
                time.sleep(max(2.0, intervalo))

        self.stdout.write(self.style.SUCCESS("[PAP_WORKER] Encerrado."))

    def _processar_com_timeout(self, job: PapJobFila, timeout_seg: int) -> bool:
        """
        Executa o job em thread. Se estourar o timeout, marca erro e retorna True (travou).
        """
        resultado: dict = {"done": False, "exc": None}

        def _runner() -> None:
            try:
                processar_job(job)
            except Exception as exc:
                resultado["exc"] = exc
                logger.exception("[PAP_WORKER] Exceção no job %s: %s", job.id, exc)
            finally:
                resultado["done"] = True

        t = threading.Thread(target=_runner, name=f"pap-job-{job.id}", daemon=True)
        t.start()
        t.join(timeout=max(30, timeout_seg))

        if resultado["done"]:
            return False

        # Timeout: marca job como erro (não reprocessa — provavelmente Playwright zumbi).
        try:
            def _marcar_timeout() -> None:
                force_close_db_connections()
                PapJobFila.objects.filter(
                    pk=job.id,
                    status=PapJobFila.STATUS_PROCESSANDO,
                ).update(
                    status=PapJobFila.STATUS_ERRO,
                    concluido_em=timezone.now(),
                    erro=(
                        f"Job abandonado: timeout de {timeout_seg}s no worker PAP "
                        f"(tipo={job.tipo})."
                    )[:4000],
                )

            retry_on_db_connection_error(
                _marcar_timeout,
                label=f"pap_job_{job.id}_timeout",
            )
        except Exception:
            logger.exception("[PAP_WORKER] Falha ao marcar timeout do job %s", job.id)

        # Avisa o usuário e libera BO do telefone deste job (não esperar 30 min do pool).
        try:
            _notificar_falha_definitiva(job)
        except Exception:
            logger.exception(
                "[PAP_WORKER] Falha ao notificar timeout do job %s",
                job.id,
            )
        try:
            from crm_app.models import PapBoEmUso
            from crm_app.pool_bo_pap import limpar_sessoes_expiradas

            telefone = str(
                (job.payload or {}).get("telefone") or job.telefone or ""
            ).strip()
            if telefone:
                deletados, _ = PapBoEmUso.objects.filter(
                    vendedor_telefone=telefone
                ).delete()
                if deletados:
                    logger.info(
                        "[PAP_WORKER] BO liberado após timeout do job %s telefone=%s",
                        job.id,
                        telefone,
                    )
            limpar_sessoes_expiradas()
        except Exception:
            logger.exception(
                "[PAP_WORKER] Falha ao liberar BO após timeout do job %s",
                job.id,
            )

        return True
