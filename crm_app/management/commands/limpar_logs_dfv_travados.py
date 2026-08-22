# crm_app/management/commands/limpar_logs_dfv_travados.py
from django.core.management.base import BaseCommand
from crm_app.models import LogImportacaoDFV
from django.db import transaction
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Remove logs de importação DFV travados (PROCESSANDO há mais de X minutos) e logs de falha'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutos',
            type=int,
            default=30,
            help='Tempo em minutos para considerar um log como travado (padrão: 30)',
        )
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Confirma a exclusão permanente dos logs travados e de falha.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula a operação sem deletar nada.',
        )
        parser.add_argument(
            '--apenas-travados',
            action='store_true',
            help='Remove apenas logs travados (PROCESSANDO), mantendo logs de falha.',
        )
        parser.add_argument(
            '--apenas-falhas',
            action='store_true',
            help='Remove apenas logs de falha, mantendo logs travados.',
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.WARNING("LIMPEZA DE LOGS DFV - TRAVADOS E FALHAS"))
        self.stdout.write("=" * 60)
        
        minutos = options['minutos']
        agora = timezone.now()
        limite_tempo = agora - timedelta(minutes=minutos)
        
        # Contar logs por status
        total_logs = LogImportacaoDFV.objects.count()
        logs_sucesso = LogImportacaoDFV.objects.filter(status='SUCESSO').count()
        logs_processando = LogImportacaoDFV.objects.filter(status='PROCESSANDO').count()
        logs_travados = LogImportacaoDFV.objects.filter(
            status='PROCESSANDO',
            iniciado_em__lt=limite_tempo
        ).count()
        logs_falhas = LogImportacaoDFV.objects.exclude(status__in=['SUCESSO', 'PROCESSANDO']).count()
        
        self.stdout.write(f"\nTotal de logs no banco: {total_logs}")
        self.stdout.write(self.style.SUCCESS(f"Logs com SUCESSO (serão mantidos): {logs_sucesso}"))
        self.stdout.write(f"Logs PROCESSANDO (total): {logs_processando}")
        self.stdout.write(self.style.WARNING(f"Logs PROCESSANDO há mais de {minutos}min (travados): {logs_travados}"))
        self.stdout.write(self.style.WARNING(f"Logs de falha (ERRO/PARCIAL): {logs_falhas}"))
        
        # Determinar quais logs serão deletados
        logs_para_deletar = LogImportacaoDFV.objects.none()
        
        if not options['apenas_falhas']:
            # Adicionar logs travados
            logs_travados_qs = LogImportacaoDFV.objects.filter(
                status='PROCESSANDO',
                iniciado_em__lt=limite_tempo
            )
            logs_para_deletar = logs_para_deletar | logs_travados_qs
        
        if not options['apenas_travados']:
            # Adicionar logs de falha
            logs_falhas_qs = LogImportacaoDFV.objects.exclude(status__in=['SUCESSO', 'PROCESSANDO'])
            logs_para_deletar = logs_para_deletar | logs_falhas_qs
        
        total_para_deletar = logs_para_deletar.count()
        
        if total_para_deletar == 0:
            self.stdout.write(self.style.SUCCESS("\nNenhum log para deletar encontrado."))
            return
        
        # Listar logs que serão deletados
        logs_lista = logs_para_deletar.order_by('-iniciado_em')
        
        self.stdout.write(f"\nLogs que serão deletados ({total_para_deletar}):")
        self.stdout.write("-" * 60)
        for log in logs_lista[:20]:  # Mostrar apenas os 20 primeiros
            tempo_decorrido = (agora - log.iniciado_em).total_seconds() / 60
            self.stdout.write(
                f"  - ID {log.id}: {log.nome_arquivo} | {log.status} | "
                f"{log.iniciado_em.strftime('%d/%m/%Y %H:%M')} | "
                f"{int(tempo_decorrido)}min atrás"
            )
        if total_para_deletar > 20:
            self.stdout.write(f"  ... e mais {total_para_deletar - 20} log(s)")
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("\n[MODO DRY-RUN] Nenhum log foi deletado."))
            self.stdout.write("Execute sem '--dry-run' para realmente deletar.")
            return
        
        if not options['confirmar']:
            self.stdout.write(self.style.WARNING("\nMODO SIMULACAO - Nenhum log foi deletado"))
            self.stdout.write("Para realmente deletar, execute:")
            self.stdout.write(f"  python manage.py {self.name} --confirmar --minutos {minutos}")
            if options['apenas_travados']:
                self.stdout.write("  (ou adicione --apenas-travados ou --apenas-falhas)")
            return
        
        self.stdout.write(self.style.WARNING("\nDELETANDO LOGS..."))
        
        with transaction.atomic():
            deleted_count = logs_para_deletar.count()
            logs_para_deletar.delete()
            
            self.stdout.write(self.style.SUCCESS(f"\nOK: {deleted_count} log(s) deletado(s)"))
            self.stdout.write(self.style.SUCCESS(f"Logs com SUCESSO mantidos: {logs_sucesso}"))
            self.stdout.write(f"Logs restantes no banco: {LogImportacaoDFV.objects.count()}")
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Limpeza concluida com sucesso!"))
        self.stdout.write("=" * 60)
