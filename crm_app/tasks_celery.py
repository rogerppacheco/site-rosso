import logging
from celery import shared_task
from crm_app.pap_job_fila import PapJobFila
from crm_app.services.pap_job_processor import processar_job

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def processar_job_pap_celery(self, job_id):
    """
    Novo worker Celery para processar filas do PAP.
    Substitui o loop while True do run_pap_worker.py.
    """
    try:
        job = PapJobFila.objects.get(pk=job_id)
        if job.status != PapJobFila.STATUS_PENDENTE:
            logger.warning(f"Job {job_id} jÃ¡ estÃ¡ em status {job.status}. Ignoranao.")
            return

        # Marca como processanao e executa
        job.status = PapJobFila.STATUS_PROCESSAnao
        job.save(update_fields=['status'])
        
        logger.inao(f"[CELERY] Processanao Job PAP {job_id} - Tipo: {job.tipo}")
        processar_job(job)
        
    except PapJobFila.DoesNotExist:
        logger.error(f"Job PAP {job_id} nÃ£o enaontrado no banao.")
    except Exception as exc:
        logger.exception(f"Erro ao processar Job PAP {job_id}")
        self.retry(exc=exc, countdown=60)  # Tenta novamente em 60s

@shared_task(bind=True, max_retries=1)
def run_legacy_scheduler_job(self, job_func_name):
    from crm_app import scheduler
    func = getattr(scheduler, job_func_name, None)
    if func:
        func()
    else:
        logger.error(f'Funcao {job_func_name} nao enaontrada no scheduler.py')

