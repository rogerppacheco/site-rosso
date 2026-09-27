import logging
from celery import shared_task
from crm_app.pap_job_fila import PapJobFila
from crm_app.services.pap_job_processor import processar_job

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def processar_job_pap_celery(self, job_id):
    """
    Worker Celery para processar filas do PAP.
    Substitui o loop while True do run_pap_worker.py.
    """
    try:
        job = PapJobFila.objects.get(pk=job_id)
        if job.status != PapJobFila.STATUS_PENDENTE:
            logger.warning(f"Job {job_id} já está em status {job.status}. Ignorando.")
            return

        # Marca como processando e executa
        job.status = PapJobFila.STATUS_PROCESSANDO
        job.save(update_fields=['status'])
        
        logger.info(f"[CELERY] Processando Job PAP {job_id} - Tipo: {job.tipo}")
        processar_job(job)
        
    except PapJobFila.DoesNotExist:
        logger.error(f"Job PAP {job_id} não encontrado no banco.")
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
        logger.error(f'Funcao {job_func_name} nao encontrada no scheduler.py')


@shared_task(bind=True, max_retries=0)
def varrer_jobs_pendentes_pap(self):
    """
    Varredura periódica da tabela PapJobFila no PostgreSQL.
    Captura jobs que ficaram 'pendente' porque o .delay() do webhook
    falhou (ex: Redis Connection refused no container do webhook).
    Re-despacha cada um diretamente via processar_job_pap_celery.delay().
    """
    from django.utils import timezone
    from datetime import timedelta

    # Busca jobs pendentes criados há mais de 10 segundos (evita conflito com dispatch normal)
    limite = timezone.now() - timedelta(seconds=10)
    jobs_pendentes = (
        PapJobFila.objects
        .filter(status=PapJobFila.STATUS_PENDENTE, criado_em__lte=limite)
        .order_by('prioridade', 'criado_em')[:10]
    )
    
    count = 0
    for job in jobs_pendentes:
        try:
            processar_job_pap_celery.delay(job.id)
            count += 1
            logger.info(f"[VARREDURA] Re-despachado job {job.id} tipo={job.tipo}")
        except Exception as e:
            logger.error(f"[VARREDURA] Falha ao re-despachar job {job.id}: {e}")
    
    if count:
        logger.info(f"[VARREDURA] {count} job(s) pendente(s) re-despachado(s).")
