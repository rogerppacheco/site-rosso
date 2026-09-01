from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from usuarios.models import Perfil, Usuario


class GestaoAcessosCadastroTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_vend = Perfil.objects.create(cod_perfil="VEND", nome="Vendedor")
        cls.grupo_vend = Group.objects.create(name="Vendedor")
        cls.operador = Usuario.objects.create_user(
            username="bo_acessos",
            password="SenhaSegura123",
            email="bo@example.com",
            pode_gestao_acessos=True,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.operador)

    def _payload(self, **overrides):
        data = {
            "username": "MARCELO.LARANJO",
            "first_name": "MARCELO",
            "last_name": "LARANJO",
            "email": "marcelo.laranjo@example.com",
            "password": "SenhaSegura123",
            "groups": [self.grupo_vend.id],
            "tel_whatsapp": "37935052153",
            "valor_almoco": None,
            "valor_passagem": None,
            "desconto_boleto": None,
            "desconto_inclusao_viabilidade": None,
            "desconto_instalacao_antecipada": None,
            "adiantamento_cnpj": None,
            "desconto_inss_fixo": None,
            "meta_comissao": None,
            "brpronto_login": None,
            "brpronto_dominio": "BrPronto",
        }
        data.update(overrides)
        return data

    def test_cadastro_aceita_financeiro_nulo_e_brpronto_vazio(self):
        resposta = self.client.post("/api/gestao-acessos/usuarios/", self._payload(), format="json")
        self.assertEqual(resposta.status_code, status.HTTP_201_CREATED, resposta.data)
        criado = Usuario.objects.get(username="MARCELO.LARANJO")
        self.assertEqual(criado.valor_almoco, 0)
        self.assertEqual(criado.meta_comissao, 0)
        self.assertTrue(criado.check_password("SenhaSegura123"))

    def test_login_com_espaco_retorna_mensagem_clara(self):
        resposta = self.client.post(
            "/api/gestao-acessos/usuarios/",
            self._payload(username="MARCELO LARANJO"),
            format="json",
        )
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("espaços", str(resposta.data.get("detail") or resposta.data))
        self.assertFalse(Usuario.objects.filter(username="MARCELO LARANJO").exists())

    def test_cadastro_sem_senha_retorna_erro(self):
        payload = self._payload()
        payload.pop("password")
        resposta = self.client.post("/api/gestao-acessos/usuarios/", payload, format="json")
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("senha", str(resposta.data).lower())
