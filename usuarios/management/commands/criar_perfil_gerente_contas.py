"""
Cria o perfil Gerente de Contas com permissões somente leitura.

Uso: python manage.py criar_perfil_gerente_contas
"""
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from crm_app.models import Venda
from crm_app.perfis_acesso import PERFIL_GERENTE_CONTAS
from usuarios.models import Perfil


PERMISSOES_LEITURA: list[str] = [
    'view_venda',
    'can_view_auditoria',
    'can_view_esteira',
]


class Command(BaseCommand):
    help = 'Cria o perfil e grupo Gerente de Contas (somente leitura)'

    def handle(self, *args, **options) -> None:
        perfil, perfil_criado = Perfil.objects.get_or_create(
            cod_perfil='gerente_contas',
            defaults={
                'nome': PERFIL_GERENTE_CONTAS,
                'descricao': (
                    'Visualização de Performance, Esteira, Auditoria e Dashboard FPD (Qualidade). '
                    'Sem permissão de edição.'
                ),
            },
        )
        if perfil_criado:
            self.stdout.write(self.style.SUCCESS(f'Perfil criado: {perfil.nome}'))
        else:
            self.stdout.write(f'Perfil já existe: {perfil.nome}')

        grupo, grupo_criado = Group.objects.get_or_create(name=PERFIL_GERENTE_CONTAS)
        if grupo_criado:
            self.stdout.write(self.style.SUCCESS(f'Grupo criado: {grupo.name}'))
        else:
            self.stdout.write(f'Grupo já existe: {grupo.name}')

        ct = ContentType.objects.get_for_model(Venda)
        permissoes = Permission.objects.filter(
            content_type=ct,
            codename__in=PERMISSOES_LEITURA,
        )
        encontradas = set(permissoes.values_list('codename', flat=True))
        faltantes = set(PERMISSOES_LEITURA) - encontradas
        if faltantes:
            self.stdout.write(
                self.style.WARNING(
                    f'Permissões não encontradas (rode migrate/criar_permissoes_faltantes): {sorted(faltantes)}'
                )
            )

        grupo.permissions.set(permissoes)
        self.stdout.write(
            self.style.SUCCESS(
                f'Permissões atribuídas ao grupo ({len(encontradas)}): {", ".join(sorted(encontradas))}'
            )
        )
        self.stdout.write(self.style.SUCCESS('\nPerfil Gerente de Contas configurado com sucesso.'))
