"""Número sem usuário ativo não usa funções do bot."""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from crm_app.models import SessaoWhatsapp
from crm_app.whatsapp_webhook_handler import (
    MSG_TELEFONE_SEM_USUARIO_ATIVO,
    processar_webhook_whatsapp,
)


class NumeroSemUsuarioAtivoTests(TestCase):
    def test_dfv_de_numero_desconhecido_recebe_aviso_e_nao_abre_fluxo(self):
        telefone = "5531988887777"
        SessaoWhatsapp.objects.create(
            telefone="31988887777",
            etapa="dfv_cep",
            dados_temp={"qualquer": True},
        )
        enviadas = []

        def _capturar(self, destino, texto, *args, **kwargs):
            enviadas.append((destino, texto))
            return True, {"messageId": "teste"}

        with (
            patch(
                "crm_app.whatsapp_webhook_handler._usuario_ativo_por_telefone",
                return_value=None,
            ),
            patch(
                "crm_app.cliente_atendimento_ia_service.processar_mensagem_cliente_venda",
                return_value=None,
            ),
            patch(
                "crm_app.whatsapp_service.WhatsAppService.enviar_mensagem_texto",
                _capturar,
            ),
        ):
            resultado = processar_webhook_whatsapp(
                {
                    "phone": telefone,
                    "type": "ReceivedCallback",
                    "text": {"message": "DFV"},
                }
            )

        self.assertEqual(resultado["status"], "ok")
        self.assertEqual(resultado["mensagem"], "Número sem usuário ativo")
        self.assertTrue(enviadas)
        self.assertIn(MSG_TELEFONE_SEM_USUARIO_ATIVO, enviadas[-1][1])
        sessao = SessaoWhatsapp.objects.get(telefone="31988887777")
        self.assertEqual(sessao.etapa, "inicial")
        self.assertEqual(sessao.dados_temp, {})

    def test_usuario_ativo_nao_recebe_aviso_de_cadastro(self):
        usuario = MagicMock()
        usuario.autorizado_chamar_no_bot = True
        usuario.id = 1
        enviadas = []

        def _capturar(self, destino, texto, *args, **kwargs):
            enviadas.append(texto)
            return True, {"messageId": "teste"}

        with (
            patch(
                "crm_app.whatsapp_webhook_handler._usuario_ativo_por_telefone",
                return_value=usuario,
            ),
            patch(
                "crm_app.whatsapp_service.WhatsAppService.enviar_mensagem_texto",
                _capturar,
            ),
            patch(
                "crm_app.whatsapp_webhook_handler._registrar_estatistica",
            ),
        ):
            resultado = processar_webhook_whatsapp(
                {
                    "phone": "5531977776666",
                    "type": "ReceivedCallback",
                    "text": {"message": "DFV"},
                }
            )

        self.assertEqual(resultado["status"], "ok")
        self.assertNotEqual(resultado.get("mensagem"), "Número sem usuário ativo")
        self.assertFalse(
            any(MSG_TELEFONE_SEM_USUARIO_ATIVO in (t or "") for t in enviadas)
        )
