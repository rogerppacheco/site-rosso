from unittest.mock import MagicMock

from django.test import SimpleTestCase

from crm_app.perfis_acesso import is_somente_leitura


def _user(is_superuser=False, groups=None, perfil_nome=None):
    user = MagicMock()
    user.is_superuser = is_superuser
    group_names = list(groups or [])

    def _filter(*, name__in=None, **kwargs):
        wanted = list(name__in or [])
        result = MagicMock()
        result.exists.return_value = any(n in group_names for n in wanted)
        return result

    user.groups.filter.side_effect = _filter
    if perfil_nome:
        user.perfil_id = 1
        user.perfil.nome = perfil_nome
    else:
        user.perfil_id = None
        user.perfil = None
    return user


class IsSomenteLeituraTests(SimpleTestCase):
    def test_superuser_pode_editar(self):
        self.assertFalse(is_somente_leitura(_user(is_superuser=True, groups=['Admin'])))

    def test_superuser_sem_grupo_pode_editar(self):
        self.assertFalse(is_somente_leitura(_user(is_superuser=True)))

    def test_admin_pode_editar(self):
        self.assertFalse(is_somente_leitura(_user(groups=['Admin'], perfil_nome='Admin')))

    def test_diretoria_pode_editar(self):
        self.assertFalse(is_somente_leitura(_user(groups=['Diretoria'], perfil_nome='Diretoria')))

    def test_backoffice_pode_editar(self):
        self.assertFalse(is_somente_leitura(_user(groups=['BackOffice'], perfil_nome='BackOffice')))

    def test_gerente_contas_somente_leitura(self):
        self.assertTrue(
            is_somente_leitura(
                _user(groups=['Gerente de Contas'], perfil_nome='Gerente de Contas')
            )
        )

    def test_admin_com_grupo_gc_ainda_pode_editar(self):
        self.assertFalse(
            is_somente_leitura(
                _user(groups=['Admin', 'Gerente de Contas'], perfil_nome='Admin')
            )
        )

    def test_vendedor_nao_e_somente_leitura(self):
        self.assertFalse(is_somente_leitura(_user(groups=['Vendedor'], perfil_nome='Vendedor')))
