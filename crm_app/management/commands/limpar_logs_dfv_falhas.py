# crm_app/management/commands/limpar_logs_dfv_falhas.py
from django.core.management.base import BaseCommand
from crm_app.models import LogImportacaoDFV
from django.db import transaction


class Command(BaseCommand):
    help = 'Remove logs de importação DFV que não tiveram sucesso, mantendo apenas os com status SUCESSO'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Confirma a exclusão permanente dos logs de falha.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula a operação sem deletar nada.',
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.WARNING("LIMPEZA DE LOGS DFV - APENAS FALHAS"))
        self.stdout.write("=" * 60)
        
        # Contar logs por status
        total_logs = LogImportacaoDFV.objects.count()
        logs_sucesso = LogImportacaoDFV.objects.filter(status='SUCESSO').count()
        logs_falhas = LogImportacaoDFV.objects.exclude(status='SUCESSO').count()
        
        self.stdout.write(f"\nTotal de logs no banco: {total_logs}")
        self.stdout.write(self.style.SUCCESS(f"Logs com SUCESSO (serão mantidos): {logs_sucesso}"))
        self.stdout.write(self.style.WARNING(f"Logs de falha (serão deletados): {logs_falhas}"))
        
        if logs_falhas == 0:
            self.stdout.write(self.style.SUCCESS("\nNenhum log de falha encontrado. Nada a fazer."))
            return
        
        # Listar logs que serão deletados
        logs_para_deletar = LogImportacaoDFV.objects.exclude(status='SUCESSO').order_by('-iniciado_em')
        
        self.stdout.write(f"\nLogs que serão deletados:")
        self.stdout.write("-" * 60)
        for log in logs_para_deletar[:10]:  # Mostrar apenas os 10 primeiros
            self.stdout.write(f"  - {log.nome_arquivo} | {log.status} | {log.iniciado_em.strftime('%d/%m/%Y %H:%M')}")
        if logs_falhas > 10:
            self.stdout.write(f"  ... e mais {logs_falhas - 10} log(s)")
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("\n[MODO DRY-RUN] Nenhum log foi deletado."))
            self.stdout.write("Execute sem '--dry-run' para realmente deletar.")
            return
        
        if not options['confirmar']:
            self.stdout.write(self.style.WARNING("\nMODO SIMULACAO - Nenhum log foi deletado"))
            self.stdout.write("Para realmente deletar, execute:")
            self.stdout.write(f"  python manage.py {self.name} --confirmar")
            return
        
        self.stdout.write(self.style.WARNING("\nDELETANDO LOGS DE FALHA..."))
        
        with transaction.atomic():
            deleted_count = logs_para_deletar.count()
            logs_para_deletar.delete()
            
            self.stdout.write(self.style.SUCCESS(f"\nOK: {deleted_count} log(s) de falha deletado(s)"))
            self.stdout.write(self.style.SUCCESS(f"Logs com SUCESSO mantidos: {logs_sucesso}"))
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Limpeza concluida com sucesso!"))
        self.stdout.write("=" * 60)
