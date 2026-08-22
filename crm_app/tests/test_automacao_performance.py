from rest_framework import status
from rest_framework.test import APITestCase

from crm_app.models import AgendamentoDisparo
from usuarios.models import Perfil, Usuario


class ConfigurarAutomacaoPerformanceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_admin = Perfil.objects.create(nome="Admin", cod_perfil="ADMIN")
        cls.usuario_admin = Usuario.objects.create_user(
            username="admin_automacao_teste",
            password="SenhaSegura123",
            perfil=cls.perfil_admin,
        )

    def setUp(self):
        self.client.force_authenticate(user=self.usuario_admin)
        self.url = "/api/crm/automacao-performance/"

    def test_modo_especifico_semanal_exige_dias_semana(self):
        payload = {
            "acao": "salvar",
            "dados": {
                "nome": "Regra Semanal sem Dias",
                "tipo": "SEMANAL",
                "modo_envio": "ESPECIFICO",
                "canal_alvo": "TODOS",
                "cluster_alvo": "",
                "destinatarios": "5511999999999",
                "ativo": True,
                "horarios_especificos": ["08:00", "10:30"],
                "dias_semana": [],
                "tipo_relatorio": "HOJE",
                "status_destinatarios": "somente_ativos",
                "prioridade": 1,
            },
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("dia", str(response.data).lower())

    def test_modo_especifico_limpa_intervalo_e_hora_fim(self):
        payload = {
            "acao": "salvar",
            "dados": {
                "nome": "Regra Específica",
                "tipo": "SEMANAL",
                "modo_envio": "ESPECIFICO",
                "canal_alvo": "PAP",
                "cluster_alvo": "CLUSTER_1",
                "destinatarios": "5511999999999,1203630@g.us",
                "ativo": True,
                "intervalo_minutos": 15,
                "hora_fim": 22,
                "horarios_especificos": ["10:40", "08:00", "10:40"],
                "dias_semana": [4, 1, 4],
                "tipo_relatorio": "SEMANAL",
                "status_destinatarios": "todos",
                "prioridade": 2,
            },
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        regra = AgendamentoDisparo.objects.get(nome="Regra Específica")
        self.assertEqual(regra.modo_envio, "ESPECIFICO")
        self.assertIsNone(regra.intervalo_minutos)
        self.assertIsNone(regra.hora_fim)
        self.assertEqual(regra.horarios_especificos, ["08:00", "10:40"])
        self.assertEqual(regra.dias_semana, [1, 4])
        self.assertEqual(regra.status_destinatarios, "todos")
        self.assertEqual(regra.prioridade, 2)

    def test_prioridade_obrigatoria(self):
        payload = {
            "acao": "salvar",
            "dados": {
                "nome": "Regra sem prioridade",
                "tipo": "HORARIO",
                "modo_envio": "INTERVALO",
                "canal_alvo": "TODOS",
                "cluster_alvo": "",
                "destinatarios": "5511999999999",
                "ativo": True,
                "intervalo_minutos": 60,
                "hora_fim": 19,
                "tipo_relatorio": "HOJE",
                "status_destinatarios": "somente_ativos",
            },
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("prioridade", str(response.data).lower())
