from django.contrib.auth.models import Group
from django.test import TestCase

from crm_app.models import PapBoEmUso
from crm_app.pool_bo_pap import (
    MSG_TODOS_ACESSOS_EM_USO,
    obter_login_bo,
)
from usuarios.models import Usuario


class PoolBoPapTests(TestCase):
    def setUp(self) -> None:
        grupo = Group.objects.create(name="BackOffice")
        self.bo = Usuario.objects.create_user(
            username="bo_teste",
            password="senha-login",
            matricula_pap="12345",
            senha_pap="senha-pap",
            login_pap_disponivel_para_automacao=True,
            pap_automacao_credito=True,
        )
        self.bo.groups.add(grupo)

    def test_aloca_bo_pelo_grupo_sem_perfil_legado(self) -> None:
        bo, erro = obter_login_bo(
            "5531999999999",
            tipo_automacao="credito",
        )

        self.assertEqual(bo, self.bo)
        self.assertIsNone(erro)
        self.assertTrue(
            PapBoEmUso.objects.filter(
                bo_usuario=self.bo,
                tipo_automacao="credito",
            ).exists()
        )

    def test_informa_ocupacao_quando_bo_elegivel_esta_em_uso(self) -> None:
        PapBoEmUso.objects.create(
            bo_usuario=self.bo,
            vendedor_telefone="5531888888888",
            tipo_automacao="credito",
        )

        bo, erro = obter_login_bo(
            "5531999999999",
            tipo_automacao="credito",
        )

        self.assertIsNone(bo)
        self.assertEqual(erro, MSG_TODOS_ACESSOS_EM_USO)

    def test_informa_ausencia_quando_automacao_nao_esta_liberada(self) -> None:
        self.bo.pap_automacao_credito = False
        self.bo.save(update_fields=["pap_automacao_credito"])

        bo, erro = obter_login_bo(
            "5531999999999",
            tipo_automacao="credito",
        )

        self.assertIsNone(bo)
        self.assertIn("Nenhum login BackOffice", erro or "")
