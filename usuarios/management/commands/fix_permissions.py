from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from crm_app.models import Venda 

class Command(BaseCommand):
    help = 'Cria permissões personalizadas e as atribui ao grupo BackOffice'

    def handle(self, *args, **options):
        # 1. Definir as permissões que faltam
        perms_config = [
            ('can_view_auditoria', 'Pode visualizar auditoria'),
            ('can_view_esteira', 'Pode visualizar esteira'),
            ('change_venda', 'Can change venda'), # Garante que a nativa existe e é usada
        ]

        content_type = ContentType.objects.get_for_model(Venda)

        # 2. Criar ou Obter as permissões no banco
        for codename, name in perms_config:
            perm, created = Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={'name': name}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Permissão criada: {codename}'))
            else:
                self.stdout.write(f'Permissão já existe: {codename}')

        # 3. Atribuir ao Grupo BackOffice
        try:
            grupo_bo = Group.objects.get(name='BackOffice')
        except Group.DoesNotExist:
            self.stdout.write(self.style.WARNING('Grupo BackOffice não encontrado. Criando...'))
            grupo_bo = Group.objects.create(name='BackOffice')

        perms_objs = Permission.objects.filter(
            codename__in=[p[0] for p in perms_config],
            content_type=content_type
        )
        
        grupo_bo.permissions.add(*perms_objs)
        self.stdout.write(self.style.SUCCESS(f'Permissões adicionadas ao grupo BackOffice: {[p.codename for p in perms_objs]}'))