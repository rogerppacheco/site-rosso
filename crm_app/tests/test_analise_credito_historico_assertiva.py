from __future__ import annotations

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase

from crm_app.models import AnaliseCreditoHistorico
from crm_app.pap_job_fila import PapJobFila
from crm_app.services.pap_job_processor import _notificar_falha_definitiva
from usuarios.models import Usuario


class AnaliseCreditoHistoricoAssertivaTests(TestCase):
    def test_salva_snapshot_assertiva_antes_do_resultado_pap(self) -> None:
        usuario = Usuario.objects.create_user(
            username="consulta-assertiva",
            password="senha-segura",
        )
        snapshot = {
            "telefones": ["31999999999"],
            "emails": ["cliente@example.com"],
            "endereco": {
                "cep": "30110000",
                "numero": "10",
                "referencia": "Casa",
                "logradouro": "Rua Exemplo",
            },
        }

        historico = AnaliseCreditoHistorico.objects.create(
            usuario=usuario,
            cpf_consultado="05623705600",
            telefone_solicitante="5531999999999",
            status_execucao=AnaliseCreditoHistorico.STATUS_PENDENTE,
            assertiva_consultada=True,
            assertiva_dados=snapshot,
        )

        historico.refresh_from_db()
        self.assertIsNone(historico.aprovado)
        self.assertEqual(
            historico.status_execucao,
            AnaliseCreditoHistorico.STATUS_PENDENTE,
        )
        self.assertEqual(historico.assertiva_dados, snapshot)


class PapJobFalhaNotificacaoTests(SimpleTestCase):
    @patch("crm_app.models.SessaoWhatsapp.objects.filter")
    @patch("crm_app.whatsapp_service.WhatsAppService.enviar_mensagem_texto")
    def test_avisa_usuario_e_reseta_sessao_em_falha_definitiva(
        self,
        enviar_mensagem: Mock,
        filtrar_sessao: Mock,
    ) -> None:
        job = PapJobFila(
            id=123,
            tipo="analise_credito",
            telefone="5531999999999",
            payload={"telefone": "5531999999999"},
        )

        _notificar_falha_definitiva(job)

        enviar_mensagem.assert_called_once()
        filtrar_sessao.assert_called_once_with(telefone="5531999999999")
        filtrar_sessao.return_value.update.assert_called_once_with(
            etapa="inicial",
            dados_temp={},
        )
