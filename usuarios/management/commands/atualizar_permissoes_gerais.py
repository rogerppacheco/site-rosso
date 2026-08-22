from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from crm_app.models import Venda

class Command(BaseCommand):
    help = 'Cria grupos padrão e atribui permissões automaticamente'

    def handle(self, *args, **options):
        # 1. Definir as permissões que devem existir
        perms_config = [
            # (codename, nome_legivel)
            ('can_view_auditoria', 'Pode visualizar auditoria'),
            ('can_view_esteira', 'Pode visualizar esteira'),
            ('can_view_comissao_dashboard', 'Pode visualizar card de comissão'),
            ('change_venda', 'Can change venda'),
            ('view_venda', 'Can view venda'),
        ]

        ct_venda = ContentType.objects.get_for_model(Venda)
        
        perm_objects = []
        for codename, name in perms_config:
            p, created = Permission.objects.get_or_create(
                codename=codename,
                content_type=ct_venda,
                defaults={'name': name}
            )
            perm_objects.append(p)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Criada: {codename}'))

        # 2. Configurar Grupo BackOffice
        grupo_bo, _ = Group.objects.get_or_create(name='BackOffice')
        # Adiciona tudo exceto a comissão (ou inclui se quiser que eles vejam)
        # Vamos supor que BackOffice vê tudo.
        grupo_bo.permissions.add(*perm_objects)
        self.stdout.write(self.style.SUCCESS('Permissões atualizadas para BackOffice.'))

        # 3. Configurar Grupo Diretoria (Vê tudo)
        grupo_dir, _ = Group.objects.get_or_create(name='Diretoria')
        grupo_dir.permissions.add(*perm_objects)
        self.stdout.write(self.style.SUCCESS('Permissões atualizadas para Diretoria.'))

        # 4. Configurar Grupo Supervisor (Vê apenas básico, não vê comissão global)
        grupo_sup, _ = Group.objects.get_or_create(name='Supervisor')
        # Remove permissão de comissão se existir, adiciona change_venda
        p_change = Permission.objects.get(codename='change_venda', content_type=ct_venda)
        grupo_sup.permissions.add(p_change)
        self.stdout.write(self.style.SUCCESS('Permissões atualizadas para Supervisor.'))