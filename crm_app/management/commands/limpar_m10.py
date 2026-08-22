from django.core.management.base import BaseCommand
from crm_app.models import SafraM10, ContratoM10, FaturaM10


class Command(BaseCommand):
    help = 'Limpa todos os dados das tabelas do Bônus M-10'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Confirma a exclusão de todos os dados',
        )

    def handle(self, *args, **options):
        if not options['confirmar']:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  ATENÇÃO: Este comando irá deletar TODOS os dados do Bônus M-10!\n'
                    '   - Todas as faturas\n'
                    '   - Todos os contratos\n'
                    '   - Todas as safras\n\n'
                    'Para confirmar, execute:\n'
                    'python manage.py limpar_m10 --confirmar\n'
                )
            )
            return

        self.stdout.write('Contando registros antes da exclusão...')
        
        count_faturas = FaturaM10.objects.count()
        count_contratos = ContratoM10.objects.count()
        count_safras = SafraM10.objects.count()
        
        self.stdout.write(f'  Faturas: {count_faturas}')
        self.stdout.write(f'  Contratos: {count_contratos}')
        self.stdout.write(f'  Safras: {count_safras}')
        
        self.stdout.write('\nDeletando registros...')
        
        # Deletar em ordem (respeitando foreign keys)
        FaturaM10.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'  ✓ {count_faturas} faturas deletadas'))
        
        ContratoM10.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'  ✓ {count_contratos} contratos deletados'))
        
        SafraM10.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f'  ✓ {count_safras} safras deletadas'))
        
        self.stdout.write(
            self.style.SUCCESS(
                '\n✅ Todas as tabelas do Bônus M-10 foram limpas com sucesso!\n'
            )
        )
