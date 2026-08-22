from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from crm_app.models import Cliente

class Command(BaseCommand):
    help = 'Libera permissão de visualização de clientes para os grupos'

    def handle(self, *args, **options):
        self.stdout.write('Liberando acesso a clientes...')

        # 1. Busca a permissão de "Ver Cliente" (view_cliente)
        content_type = ContentType.objects.get_for_model(Cliente)
        try:
            perm_view_cliente = Permission.objects.get(codename='view_cliente', content_type=content_type)
            perm_add_cliente = Permission.objects.get(codename='add_cliente', content_type=content_type)
        except Permission.DoesNotExist:
            self.stdout.write(self.style.ERROR('ERRO: Permissões de cliente não encontradas!'))
            return

        # 2. Grupos que precisam acessar clientes (Basicamente todos)
        grupos = ['Vendedor', 'Supervisor', 'BackOffice', 'Diretoria']

        for nome_grupo in grupos:
            try:
                grupo = Group.objects.get(name=nome_grupo)
                
                # Adiciona permissão de VER
                if not grupo.permissions.filter(id=perm_view_cliente.id).exists():
                    grupo.permissions.add(perm_view_cliente)
                    self.stdout.write(f' - Leitura de clientes liberada para: {nome_grupo}')
                
                # Adiciona permissão de CRIAR (Necessário para salvar nova venda com cliente novo)
                if not grupo.permissions.filter(id=perm_add_cliente.id).exists():
                    grupo.permissions.add(perm_add_cliente)
                    self.stdout.write(f' - Criação de clientes liberada para: {nome_grupo}')
                    
            except Group.DoesNotExist:
                pass

        self.stdout.write(self.style.SUCCESS('Pronto! O autocomplete deve funcionar agora.'))