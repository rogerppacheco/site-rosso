from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from crm_app.models import Venda

class Command(BaseCommand):
    help = 'Garante que todos os grupos tenham permissão para visualizar vendas'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando correção de permissões...')

        # 1. Busca a permissão de "Ver Venda" (view_venda)
        content_type = ContentType.objects.get_for_model(Venda)
        try:
            perm_view_venda = Permission.objects.get(codename='view_venda', content_type=content_type)
        except Permission.DoesNotExist:
            self.stdout.write(self.style.ERROR('ERRO CRÍTICO: Permissão view_venda não existe!'))
            return

        # 2. Grupos que DEVEM ter acesso a vendas
        grupos_alvo = ['Vendedor', 'Supervisor', 'BackOffice', 'Diretoria']

        for nome_grupo in grupos_alvo:
            try:
                grupo = Group.objects.get(name=nome_grupo)
                # Adiciona a permissão se não tiver
                if not grupo.permissions.filter(id=perm_view_venda.id).exists():
                    grupo.permissions.add(perm_view_venda)
                    self.stdout.write(f' - Permissão view_venda adicionada ao grupo {nome_grupo}')
                else:
                    self.stdout.write(f' - Grupo {nome_grupo} já tinha permissão.')
            except Group.DoesNotExist:
                self.stdout.write(self.style.WARNING(f' ! Grupo {nome_grupo} não encontrado.'))

        self.stdout.write(self.style.SUCCESS('Correção concluída! Tente acessar agora.'))