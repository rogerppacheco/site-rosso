"""Inbox de atendimento WhatsApp: histórico, janela de 24h e autenticação."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from crm_app.models import MensagemWhatsAppAtendimento, WhatsAppTelefoneSemIa
from crm_app.services.whatsapp.atendimento_service import (
    estado_janela,
    gravar_mensagem,
    registrar_entrada_webhook,
)
from crm_app.whatsapp_service import WhatsAppService
from crm_app.whatsapp_webhook_normalizer import normalizar_webhook
from usuarios.models import Usuario


def _payload_meta(texto="Olá, preciso de ajuda", mid="wamid.INBOX1", fone="5531999887766"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": fone,
                                    "id": mid,
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ]
                        }
                    }
                ]
            }
        ],
    }


class _ProviderOk:
    def enviar_mensagem_texto_raw(self, telefone, mensagem):
        return True, {"messageId": "wamid.OUT1", "messages": [{"id": "wamid.OUT1"}]}

    def enviar_template(self, telefone, template_name, language_code="pt_BR", body_params=None, template_params=None):
        return True, {"messageId": "wamid.TPL1"}

    def resposta_indica_sucesso(self, resp):
        return True


@override_settings(WHATSAPP_WEBHOOK_FASTPATH=True, META_APP_SECRET="", WHATSATENDE_WEBHOOK_TOKEN="")
class AtendimentoWhatsAppTests(TestCase):
    def setUp(self):
        self.grupo = Group.objects.create(name="BackOffice")
        self.user = Usuario.objects.create_user(username="bo_wa", password="segredo-teste")
        self.user.groups.add(self.grupo)
        self.vendedor = Usuario.objects.create_user(username="vend_wa", password="segredo-teste")
        self.client = APIClient()

    def _entrada(self, horas_atras=1, texto="Oi", mid="wamid.E1"):
        quando = timezone.now() - timedelta(hours=horas_atras)
        return gravar_mensagem(
            telefone="31999887766",
            direcao=MensagemWhatsAppAtendimento.DIRECAO_ENTRADA,
            texto=texto,
            tipo=MensagemWhatsAppAtendimento.TIPO_SESSAO,
            origem=MensagemWhatsAppAtendimento.ORIGEM_WEBHOOK,
            message_id=mid,
            data_hora=quando,
        )

    def test_webhook_meta_grava_entrada_e_nao_duplica(self):
        canon = normalizar_webhook(_payload_meta())
        primeiro = registrar_entrada_webhook(canon)
        segundo = registrar_entrada_webhook(canon)
        self.assertIsNotNone(primeiro)
        self.assertEqual(primeiro.id, segundo.id)
        self.assertEqual(primeiro.direcao, "ENTRADA")
        self.assertEqual(primeiro.tipo, "SESSAO")
        self.assertEqual(primeiro.telefone, "31999887766")
        self.assertEqual(MensagemWhatsAppAtendimento.objects.count(), 1)

    def test_webhook_http_grava_antes_do_fastpath(self):
        with patch(
            "crm_app.whatsapp_webhook_fastpath.avaliar_fastpath_webhook",
            return_value={"status": "ok", "mensagem": "Telefone bloqueado"},
        ):
            resp = self.client.post(
                "/api/crm/webhook-whatsapp/",
                data=_payload_meta(texto="Cheguei", mid="wamid.HTTP1"),
                format="json",
            )
        self.assertEqual(resp.status_code, 200)
        msg = MensagemWhatsAppAtendimento.objects.get(message_id="wamid.HTTP1")
        self.assertEqual(msg.texto, "Cheguei")
        self.assertEqual(msg.direcao, "ENTRADA")

    def test_saida_texto_e_modelo_no_numero_cliente(self):
        with patch("crm_app.whatsapp_service.get_whatsapp_provider", return_value=_ProviderOk()):
            svc = WhatsAppService.para_cliente()
            ok, _ = svc.enviar_mensagem_texto("31999887766", "Resposta de sessão", variar=False)
            self.assertTrue(ok)
            ok_tpl, _ = svc.enviar_template(
                "31999887766",
                "nio_boas_vindas_v1",
                body_params=["Bom dia", "Ana"],
            )
            self.assertTrue(ok_tpl)
        textos = list(MensagemWhatsAppAtendimento.objects.order_by("id"))
        self.assertEqual(len(textos), 2)
        self.assertEqual(textos[0].tipo, "SESSAO")
        self.assertEqual(textos[0].texto, "Resposta de sessão")
        self.assertEqual(textos[1].tipo, "MODELO")
        self.assertEqual(textos[1].template_name, "nio_boas_vindas_v1")
        self.assertIn("nio_boas_vindas_v1", textos[1].texto)
        self.assertIn("Ana", textos[1].texto)

    def test_envio_interno_nao_entra_no_inbox(self):
        with patch("crm_app.whatsapp_service.get_whatsapp_provider", return_value=_ProviderOk()):
            WhatsAppService().enviar_mensagem_texto("31999887766", "interno", variar=False)
        self.assertEqual(MensagemWhatsAppAtendimento.objects.count(), 0)

    def test_janela_aberta_e_fechada(self):
        self._entrada(horas_atras=1, mid="wamid.JANELA1")
        self.assertTrue(estado_janela("31999887766")["aberta"])
        MensagemWhatsAppAtendimento.objects.all().delete()
        self._entrada(horas_atras=25, mid="wamid.JANELA2")
        estado = estado_janela("31999887766")
        self.assertFalse(estado["aberta"])
        self.assertIn("modelo aprovado", estado["aviso"])

    def test_responder_exige_login_e_perfil(self):
        self._entrada()
        url = "/api/crm/atendimento-whatsapp/conversas/31999887766/responder/"
        anon = self.client.post(url, {"texto": "oi"}, format="json")
        self.assertEqual(anon.status_code, 401)
        self.client.force_authenticate(self.vendedor)
        negado = self.client.post(url, {"texto": "oi"}, format="json")
        self.assertEqual(negado.status_code, 403)

    def test_janela_fechada_nao_envia(self):
        self._entrada(horas_atras=30, mid="wamid.FECHADA")
        self.client.force_authenticate(self.user)
        with patch("crm_app.whatsapp_service.WhatsAppService.para_cliente") as mock_cli:
            resp = self.client.post(
                "/api/crm/atendimento-whatsapp/conversas/31999887766/responder/",
                {"texto": "ainda estou aqui"},
                format="json",
            )
        self.assertEqual(resp.status_code, 409)
        mock_cli.assert_not_called()
        self.assertIn("modelo aprovado", resp.json()["detail"])
        self.assertFalse(
            MensagemWhatsAppAtendimento.objects.filter(direcao="SAIDA").exists()
        )

    def test_resposta_dentro_da_janela_pausa_o_bot(self):
        self._entrada(horas_atras=1, mid="wamid.ABERTA")
        self.client.force_authenticate(self.user)
        provider = _ProviderOk()
        with patch("crm_app.whatsapp_service.get_whatsapp_provider", return_value=provider), patch(
            "crm_app.services.whatsapp_config_service.canal_cliente_pronto", return_value=True
        ), patch(
            "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
            return_value="meta",
        ):
            resp = self.client.post(
                "/api/crm/atendimento-whatsapp/conversas/31999887766/responder/",
                {"texto": "Olá, sou do atendimento."},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        corpo = resp.json()
        self.assertTrue(corpo["bot_pausado"])
        self.assertTrue(corpo["conversa"]["janela_aberta"])
        textos = [m["texto"] for m in corpo["conversa"]["mensagens"]]
        self.assertIn("Olá, sou do atendimento.", textos)
        self.assertTrue(
            WhatsAppTelefoneSemIa.objects.filter(telefone="31999887766", ativo=True).exists()
        )
        saida = MensagemWhatsAppAtendimento.objects.get(direcao="SAIDA")
        self.assertEqual(saida.origem, "OPERADOR")
        self.assertEqual(saida.enviado_por_id, self.user.id)
        self.assertEqual(saida.tipo, "SESSAO")

    def test_canal_oficial_indisponivel_nao_envia_pelo_numero_comercial(self):
        self._entrada(horas_atras=1, mid="wamid.SEMCANAL")
        self.client.force_authenticate(self.user)
        cenarios = (
            ("canal_nao_liberado", False, "meta"),
            ("provedor_zapi", True, "zapi"),
            ("provedor_evolution", True, "evolution"),
        )
        for nome, pronto, provedor in cenarios:
            with self.subTest(nome), patch(
                "crm_app.whatsapp_service.WhatsAppService.para_cliente"
            ) as mock_cli, patch(
                "crm_app.services.whatsapp_config_service.canal_cliente_pronto",
                return_value=pronto,
            ), patch(
                "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
                return_value=provedor,
            ):
                resp = self.client.post(
                    "/api/crm/atendimento-whatsapp/conversas/31999887766/responder/",
                    {"texto": "Olá"},
                    format="json",
                )
                detalhe = self.client.get("/api/crm/atendimento-whatsapp/conversas/31999887766/")
                self.assertEqual(resp.status_code, 503)
                mock_cli.assert_not_called()
                self.assertFalse(
                    MensagemWhatsAppAtendimento.objects.filter(direcao="SAIDA").exists()
                )
                self.assertFalse(
                    WhatsAppTelefoneSemIa.objects.filter(telefone="31999887766", ativo=True).exists()
                )
                self.assertTrue(detalhe.json()["janela_aberta"])
                self.assertFalse(detalhe.json()["canal_oficial_pronto"])
                self.assertFalse(detalhe.json()["pode_texto_livre"])

    def test_lista_mostra_direcao_e_tipo(self):
        self._entrada(texto="Quero saber da instalação", mid="wamid.LISTA")
        self.client.force_authenticate(self.user)
        resp = self.client.get("/api/crm/atendimento-whatsapp/conversas/")
        self.assertEqual(resp.status_code, 200)
        item = resp.json()["items"][0]
        self.assertEqual(item["ultima_direcao"], "ENTRADA")
        self.assertEqual(item["ultima_tipo"], "SESSAO")
        self.assertIn("instalação", item["ultima_mensagem"])

    def test_pagina_existe(self):
        resp = self.client.get("/atendimento-whatsapp/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Atendimento WhatsApp")
        self.assertContains(resp, "janela de 24 horas")
