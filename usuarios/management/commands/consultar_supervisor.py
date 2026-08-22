from django.core.management.base import BaseCommand
from usuarios.models import Usuario


class Command(BaseCommand):
    help = 'Consulta o supervisor de um usuário específico'

    def add_arguments(self, parser):
        parser.add_argument('nome', type=str, help='Nome do usuário a consultar')

    def handle(self, *args, **options):
        nome_busca = options['nome'].upper()
        
        # Buscar o usuário
        user = Usuario.objects.filter(
            first_name__icontains='BRUNO',
            last_name__icontains='FRANCA'
        ).select_related('supervisor').first()

        if not user:
            # Tentar busca mais ampla
            partes = nome_busca.split()
            if len(partes) >= 2:
                user = Usuario.objects.filter(
                    first_name__icontains=partes[0]
                ).filter(
                    last_name__icontains=partes[-1]
                ).select_related('supervisor').first()

        if user:
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write(self.style.SUCCESS('USUARIO ENCONTRADO:'))
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write(f'Nome Completo: {user.get_full_name()}')
            self.stdout.write(f'Username: {user.username}')
            self.stdout.write(f'ID: {user.id}')
            self.stdout.write(f'Email: {user.email or "N/A"}')
            self.stdout.write(f'Ativo: {"Sim" if user.is_active else "Nao"}')
            self.stdout.write('')
            
            if user.supervisor:
                self.stdout.write(self.style.SUCCESS('=' * 60))
                self.stdout.write(self.style.SUCCESS('SUPERVISOR:'))
                self.stdout.write(self.style.SUCCESS('=' * 60))
                self.stdout.write(f'Nome Completo: {user.supervisor.get_full_name()}')
                self.stdout.write(f'Username: {user.supervisor.username}')
                self.stdout.write(f'ID: {user.supervisor.id}')
                self.stdout.write(f'Email: {user.supervisor.email or "N/A"}')
            else:
                self.stdout.write(self.style.WARNING('=' * 60))
                self.stdout.write(self.style.WARNING('SUPERVISOR: NENHUM'))
                self.stdout.write(self.style.WARNING('Usuario nao tem supervisor atribuido'))
                self.stdout.write(self.style.WARNING('=' * 60))
        else:
            self.stdout.write(self.style.ERROR('=' * 60))
            self.stdout.write(self.style.ERROR('USUARIO NAO ENCONTRADO'))
            self.stdout.write(self.style.ERROR('=' * 60))
            
            # Listar usuários similares
            usuarios_bruno = Usuario.objects.filter(
                first_name__icontains='BRUNO'
            ) | Usuario.objects.filter(
                last_name__icontains='BRUNO'
            )
            
            if usuarios_bruno.exists():
                self.stdout.write(f'\nEncontrados {usuarios_bruno.count()} usuarios com "BRUNO" no nome:')
                for u in usuarios_bruno[:10]:  # Limitar a 10
                    self.stdout.write(f'  - {u.get_full_name()} (ID: {u.id}, Username: {u.username})')
