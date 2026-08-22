"""
Comando para limpar todos os registros DFV do banco de dados.
Uso: python manage.py limpar_dfv
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from crm_app.models import DFV, LogImportacaoDFV


class Command(BaseCommand):
    help = 'Limpa todos os registros DFV do banco de dados'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Confirma a exclusão (sem isso, apenas mostra quantos registros seriam deletados)',
        )
        parser.add_argument(
            '--incluir-logs',
            action='store_true',
            help='Também exclui os logs de importação DFV',
        )

    def handle(self, *args, **options):
        confirmar = options['confirmar']
        incluir_logs = options['incluir_logs']
        
        # Contar registros
        total_dfv = DFV.objects.count()
        total_logs = LogImportacaoDFV.objects.count()
        
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write(self.style.WARNING('ATENÇÃO: Esta operação irá DELETAR dados permanentemente!'))
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write('')
        self.stdout.write(f'Registros DFV no banco: {total_dfv:,}')
        if incluir_logs:
            self.stdout.write(f'Logs de importação DFV: {total_logs:,}')
        self.stdout.write('')
        
        if not confirmar:
            self.stdout.write(self.style.WARNING('MODO SIMULACAO - Nenhum dado foi deletado'))
            self.stdout.write('')
            self.stdout.write('Para realmente deletar, execute:')
            self.stdout.write(self.style.SUCCESS('  python manage.py limpar_dfv --confirmar'))
            if incluir_logs:
                self.stdout.write(self.style.SUCCESS('  python manage.py limpar_dfv --confirmar --incluir-logs'))
            return
        
        # Confirmar exclusão
        self.stdout.write(self.style.ERROR('DELETANDO DADOS...'))
        self.stdout.write('')
        
        try:
            with transaction.atomic():
                # Deletar registros DFV
                self.stdout.write(f'Deletando {total_dfv:,} registros DFV...')
                DFV.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f'OK: {total_dfv:,} registros DFV deletados'))
                
                # Deletar logs se solicitado
                if incluir_logs:
                    self.stdout.write(f'Deletando {total_logs:,} logs de importacao...')
                    LogImportacaoDFV.objects.all().delete()
                    self.stdout.write(self.style.SUCCESS(f'OK: {total_logs:,} logs deletados'))
                
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('=' * 60))
                self.stdout.write(self.style.SUCCESS('Limpeza concluida com sucesso!'))
                self.stdout.write(self.style.SUCCESS('=' * 60))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'ERRO ao deletar: {str(e)}'))
            import traceback
            traceback.print_exc()
