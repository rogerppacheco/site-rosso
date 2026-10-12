from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from crm_app.models import Cliente, FilaEnvioBoasVindas, Venda


@override_settings(BOAS_VINDAS_MAX_ATRASO_HORAS=24)
class FilaBoasVindasAtrasoTests(TestCase):
    def setUp(self):
        self.agora = timezone.now()
        self.seq = 0

    def _fila(self, horas_atras):
        self.seq += 1
        cliente = Cliente.objects.create(nome_razao_social=f"Cliente {self.seq}", cpf_cnpj=f"0000000000{self.seq}")
        venda = Venda.objects.create(cliente=cliente, telefone1="31999990000")
        return FilaEnvioBoasVindas.objects.create(
            venda=venda,
            data_instalacao=self.agora.date(),
            agendado_para=self.agora - timedelta(hours=horas_atras),
        )

    @patch("crm_app.management.commands.processar_fila_boas_vindas.WhatsAppService")
    def test_envio_atrasado_expira_sem_enviar(self, svc_cls):
        svc_cls.return_value.enviar_mensagem_texto.return_value = (True, {})
        atrasado = self._fila(horas_atras=72)
        recente = self._fila(horas_atras=1)

        call_command("processar_fila_boas_vindas", "--limite", "5")

        atrasado.refresh_from_db()
        recente.refresh_from_db()
        self.assertIsNone(atrasado.enviado_em)
        self.assertTrue(atrasado.erro.startswith("Expirado"))
        self.assertIsNotNone(recente.enviado_em)
        self.assertEqual(svc_cls.return_value.enviar_mensagem_texto.call_count, 1)

        call_command("processar_fila_boas_vindas", "--limite", "5")
        self.assertEqual(svc_cls.return_value.enviar_mensagem_texto.call_count, 1)

    @patch("crm_app.management.commands.processar_fila_boas_vindas.WhatsAppService")
    def test_dry_run_nao_marca_expirado(self, svc_cls):
        atrasado = self._fila(horas_atras=72)

        call_command("processar_fila_boas_vindas", "--dry-run")

        atrasado.refresh_from_db()
        self.assertIsNone(atrasado.erro)
        svc_cls.return_value.enviar_mensagem_texto.assert_not_called()
