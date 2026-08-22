"""
Processo dedicado do APScheduler (separado do Gunicorn).

Uso local (segundo terminal):
    python manage.py run_scheduler

Railway: segundo serviço com start command acima e replicas=1.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Inicia o agendador de tarefas em processo dedicado (bloqueante)'

    def handle(self, *args, **options):
        from crm_app.scheduler import run_blocking_scheduler

        self.stdout.write(self.style.SUCCESS(
            'Iniciando scheduler (processo dedicado). Encerre com Ctrl+C.'
        ))
        run_blocking_scheduler()
