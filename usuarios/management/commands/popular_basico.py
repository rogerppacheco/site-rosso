from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from usuarios.models import Perfil, Usuario

class Command(BaseCommand):
    help = 'Popula grupos, perfis e um usuário admin padrão'

    def handle(self, *args, **kwargs):
        grupos = ['Admin', 'Gestor', 'Vendedor', 'Supervisor', 'Financeiro']
        for nome in grupos:
            Group.objects.get_or_create(name=nome)
        self.stdout.write(self.style.SUCCESS('Grupos criados!'))

        perfis = ['Administrador', 'Gestor', 'Consultor', 'Supervisor']
        for nome in perfis:
            Perfil.objects.get_or_create(nome=nome)
        self.stdout.write(self.style.SUCCESS('Perfis criados!'))

        if not Usuario.objects.filter(username='admin').exists():
            admin = Usuario.objects.create_superuser(
                username='admin',
                email='admin@local.com',
                password='admin123',
                first_name='Admin',
                last_name='Local'
            )
            self.stdout.write(self.style.SUCCESS('Usuário admin criado!'))
        else:
            self.stdout.write('Usuário admin já existe.')
