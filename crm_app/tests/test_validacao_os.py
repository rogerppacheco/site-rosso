from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework import status

from usuarios.models import Usuario, Perfil
from crm_app.models import Cliente, Venda, StatusCRM
from crm_app.serializers import VendaUpdateSerializer


class BaseOsFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.perfil_auditoria = Perfil.objects.create(cod_perfil="AUD", nome="Auditoria")
        cls.usuario = Usuario.objects.create_user(
            username="auditor_os",
            password="SenhaSegura123",
            perfil=cls.perfil_auditoria,
        )
        cls.cliente = Cliente.objects.create(
            cpf_cnpj="12345678901",
            nome_razao_social="CLIENTE TESTE",
            email="cliente@teste.com",
        )
        cls.status_sem = StatusCRM.objects.create(nome="SEM TRATAMENTO", tipo="Tratamento")
        cls.status_cadastrada = StatusCRM.objects.create(nome="CADASTRADA", tipo="Tratamento")
        cls.status_agendado = StatusCRM.objects.create(nome="AGENDADO", tipo="Esteira")
        cls.status_instalada = StatusCRM.objects.create(nome="INSTALADA", tipo="Esteira")

    def criar_venda(self):
        return Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente,
            status_tratamento=self.status_sem,
            status_esteira=self.status_agendado,
            forma_entrada="SEM_APP",
        )


class VendaUpdateSerializerOsTests(BaseOsFixtureMixin, TestCase):
    def test_aceita_os_com_oito_digitos(self):
        venda = self.criar_venda()
        serializer = VendaUpdateSerializer(instance=venda, data={"ordem_servico": "08907507"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_aceita_os_com_padrao_x_hifen_12_digitos(self):
        venda = self.criar_venda()
        serializer = VendaUpdateSerializer(instance=venda, data={"ordem_servico": "4-212051254235"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejeita_os_formato_invalido(self):
        venda = self.criar_venda()
        serializer = VendaUpdateSerializer(instance=venda, data={"ordem_servico": "ABC123"}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("ordem_servico", serializer.errors)

    def test_rejeita_status_instalada_sem_os_valida(self):
        venda = self.criar_venda()
        serializer = VendaUpdateSerializer(
            instance=venda,
            data={"status_esteira": self.status_instalada.id, "ordem_servico": ""},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("ordem_servico", serializer.errors)


class FinalizarAuditoriaOsTests(BaseOsFixtureMixin, APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=self.usuario)

    def test_bloqueia_cadastrada_sem_os(self):
        venda = self.criar_venda()
        payload = {
            "status": "CADASTRADA",
            "observacoes": "Teste",
            "dados_atualizados": {},
        }
        response = self.client.post(f"/api/crm/vendas/{venda.id}/finalizar_auditoria/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("obrigatório informar O.S", str(response.data))

    def test_bloqueia_cadastrada_com_os_invalida(self):
        venda = self.criar_venda()
        payload = {
            "status": "CADASTRADA",
            "observacoes": "Teste",
            "dados_atualizados": {"ordem_servico": "12-123"},
        }
        response = self.client.post(f"/api/crm/vendas/{venda.id}/finalizar_auditoria/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Formato de O.S inválido", str(response.data))

    def test_permiter_cadastrada_com_os_valida(self):
        venda = self.criar_venda()
        payload = {
            "status": "CADASTRADA",
            "observacoes": "Teste",
            "dados_atualizados": {"ordem_servico": "08907507"},
        }
        response = self.client.post(f"/api/crm/vendas/{venda.id}/finalizar_auditoria/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        venda.refresh_from_db()
        self.assertEqual(venda.ordem_servico, "08907507")

    def test_bloqueia_cadastrada_os_ja_cadastrada_em_outra_venda(self):
        venda1 = self.criar_venda()
        venda2 = self.criar_venda()
        payload1 = {
            "status": "CADASTRADA",
            "observacoes": "Primeira",
            "dados_atualizados": {"ordem_servico": "08907507"},
        }
        r1 = self.client.post(f"/api/crm/vendas/{venda1.id}/finalizar_auditoria/", payload1, format="json")
        self.assertEqual(r1.status_code, status.HTTP_200_OK)

        payload2 = {
            "status": "CADASTRADA",
            "observacoes": "Duplicata",
            "dados_atualizados": {"ordem_servico": "08907507"},
        }
        r2 = self.client.post(f"/api/crm/vendas/{venda2.id}/finalizar_auditoria/", payload2, format="json")
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("já foi cadastrado", str(r2.data))

    def test_verificar_os_cadastrada_endpoint(self):
        venda = self.criar_venda()
        Venda.objects.filter(pk=venda.pk).update(ordem_servico="4-212051254235")
        venda.status_tratamento = self.status_cadastrada
        venda.save(update_fields=["status_tratamento"])

        r = self.client.get(
            "/api/crm/vendas/verificar-os-cadastrada/",
            {"ordem_servico": "4-212051254235", "venda_id": 99999},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data.get("existe"))
