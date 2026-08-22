"""Testes do normalizador de webhook Evolution e factory de provider."""
from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from crm_app.whatsapp_webhook_normalizer import (
    detectar_provedor,
    normalizar_webhook,
)
from crm_app.services.whatsapp.factory import (
    clear_whatsapp_provider_cache,
    get_whatsapp_provider,
)
from crm_app.services.whatsapp.zapi_provider import ZapiProvider
from crm_app.services.whatsapp.n8n_outbound_provider import N8nOutboundProvider
from crm_app.services.whatsapp.evolution_provider import EvolutionProvider
from crm_app.services.whatsapp.whatsatende_provider import WhatsAtendeProvider


class TestWebhookNormalizer(SimpleTestCase):
    def test_detecta_evolution_por_evento(self) -> None:
        payload = {"event": "messages.upsert", "data": {"key": {"remoteJid": "5511999999999@s.whatsapp.net"}}}
        self.assertEqual(detectar_provedor(payload), "evolution")

    def test_detecta_zapi(self) -> None:
        self.assertEqual(detectar_provedor({"phone": "5511999999999", "message": "oi"}), "zapi")

    def test_detecta_whatsatende_por_source(self) -> None:
        self.assertEqual(
            detectar_provedor({"source": "whatsatende", "contact": {}, "message": {}}),
            "whatsatende",
        )

    def test_detecta_whatsatende_payload_oficial(self) -> None:
        payload = {
            "id": "wamid.HBgMNTUzMTk5OTk5OTk5FQIAEh...",
            "type": "text",
            "message": "Olá, quero atendimento",
            "mediaUrl": None,
            "mediaType": None,
            "senderNumber": "5531999999999",
            "ticketId": 12345,
            "status": "open",
            "userId": None,
            "queueId": 10,
        }
        self.assertEqual(detectar_provedor(payload), "whatsatende")

    def test_detecta_whatsatende_por_contact_message(self) -> None:
        payload = {
            "event": "message.received",
            "contact": {"number": "5531999882528", "name": "Teste"},
            "message": {"body": "VENDER", "fromMe": False, "id": "MSG1"},
        }
        self.assertEqual(detectar_provedor(payload), "whatsatende")

    def test_normaliza_texto_evolution(self) -> None:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "5531999882528@s.whatsapp.net",
                    "fromMe": False,
                    "id": "ABC123",
                },
                "message": {"conversation": "VENDER"},
            },
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["phone"], "5531999882528")
        self.assertFalse(canon["fromMe"])
        self.assertEqual(canon["message"]["text"], "VENDER")

    def test_normaliza_texto_whatsatende_oficial(self) -> None:
        payload = {
            "id": "wamid.ABC123",
            "type": "text",
            "message": "VENDER",
            "mediaUrl": None,
            "mediaType": None,
            "senderNumber": "5531999882528",
            "ticketId": 12345,
            "status": "open",
            "userId": None,
            "queueId": 10,
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["phone"], "5531999882528")
        self.assertEqual(canon["message"]["text"], "VENDER")
        self.assertEqual(canon["type"], "ReceivedCallback")
        self.assertEqual(canon["messageId"], "wamid.ABC123")
        self.assertFalse(canon["fromMe"])

    def test_normaliza_whatsatende_enviada_pela_api_eh_from_me(self) -> None:
        payload = {
            "id": "wamid.OUT1",
            "type": "text",
            "message": "Olá! Como posso ajudar?",
            "senderNumber": "5531999882528",
            "ticketId": 1,
            "status": "open",
            "userId": 7,
            "queueId": 10,
        }
        canon = normalizar_webhook(payload)
        self.assertTrue(canon["fromMe"])

    def test_normaliza_whatsatende_midia(self) -> None:
        payload = {
            "id": "wamid.IMG1",
            "type": "image",
            "message": "Segue comprovante",
            "mediaUrl": "https://api.app14.whatsatende.com.br/public/arquivo.jpg",
            "mediaType": "image/jpeg",
            "senderNumber": "5531999999999",
            "ticketId": 12345,
            "status": "open",
            "userId": None,
            "queueId": 10,
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["image"]["imageUrl"], payload["mediaUrl"])
        self.assertEqual(canon["message"]["text"], "Segue comprovante")

    def test_status_ticket_open_nao_vira_delivery_callback(self) -> None:
        """status=open é do ticket; WhatsAtende não tem ACK público de entrega."""
        payload = {
            "id": "wamid.X",
            "type": "text",
            "message": "oi",
            "senderNumber": "5531999882528",
            "ticketId": 1,
            "status": "open",
            "userId": None,
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["type"], "ReceivedCallback")

    def test_normaliza_botao_evolution(self) -> None:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {"remoteJid": "5531999882528@s.whatsapp.net", "fromMe": False},
                "message": {
                    "buttonsResponseMessage": {
                        "selectedButtonId": "pap_confirmar_sim",
                        "selectedDisplayText": "SIM",
                    }
                },
            },
        }
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["buttonsResponseMessage"]["buttonId"], "pap_confirmar_sim")

    def test_normaliza_grupo_evolution(self) -> None:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "120363019502650977@g.us",
                    "participant": "5531999882528@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {"conversation": "123, antecipada"},
            },
        }
        canon = normalizar_webhook(payload)
        self.assertTrue(canon["isGroup"])
        self.assertIn("-group", canon["phone"])
        self.assertEqual(canon["participantPhone"], "5531999882528")


class TestProviderFactory(SimpleTestCase):
    def tearDown(self) -> None:
        clear_whatsapp_provider_cache()

    @override_settings(WHATSAPP_PROVIDER="zapi")
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="zapi",
    )
    def test_factory_zapi(self, _mock_provider: object) -> None:
        clear_whatsapp_provider_cache()
        self.assertIsInstance(get_whatsapp_provider(), ZapiProvider)

    @override_settings(WHATSAPP_PROVIDER="evolution")
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="evolution",
    )
    def test_factory_evolution(self, _mock_provider: object) -> None:
        clear_whatsapp_provider_cache()
        self.assertIsInstance(get_whatsapp_provider(), N8nOutboundProvider)

    @override_settings(WHATSAPP_PROVIDER="whatsatende", WHATSATENDE_TOKEN="tok")
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="whatsatende",
    )
    def test_factory_whatsatende(self, _mock_provider: object) -> None:
        clear_whatsapp_provider_cache()
        self.assertIsInstance(get_whatsapp_provider(), WhatsAtendeProvider)

    @override_settings(
        WHATSAPP_PROVIDER="whatsatende",
        WHATSATENDE_TOKEN="tok-a",
        WHATSATENDE_WHATSAPP_ID="196",
        WHATSATENDE_TOKEN_B="tok-b",
        WHATSATENDE_WHATSAPP_ID_B="194",
    )
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="whatsatende",
    )
    def test_factory_whatsatende_dual_ab(self, _mock_provider: object) -> None:
        from crm_app.services.whatsapp.factory import PURPOSE_CLIENTE

        clear_whatsapp_provider_cache()
        interno = get_whatsapp_provider()
        cliente = get_whatsapp_provider(purpose=PURPOSE_CLIENTE)
        self.assertIsInstance(interno, WhatsAtendeProvider)
        self.assertIsInstance(cliente, WhatsAtendeProvider)
        self.assertEqual(interno.token, "tok-a")
        self.assertEqual(interno.whatsapp_id, "196")
        self.assertEqual(cliente.token, "tok-b")
        self.assertEqual(cliente.whatsapp_id, "194")
        self.assertIsNot(interno, cliente)

    @override_settings(
        ZAPI_INSTANCE_ID="inst",
        ZAPI_TOKEN="z-tok",
        WHATSATENDE_TOKEN_B="tok-b",
        WHATSATENDE_WHATSAPP_ID_B="194",
        WHATSATENDE_TOKEN="tok-a-unused",
        WHATSATENDE_WHATSAPP_ID="196",
    )
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="hybrid",
    )
    def test_factory_hybrid_zapi_interno_whatsatende_cliente(
        self, _mock_provider: object
    ) -> None:
        from crm_app.services.whatsapp.factory import PURPOSE_CLIENTE

        clear_whatsapp_provider_cache()
        interno = get_whatsapp_provider()
        cliente = get_whatsapp_provider(purpose=PURPOSE_CLIENTE)
        self.assertIsInstance(interno, ZapiProvider)
        self.assertIsInstance(cliente, WhatsAtendeProvider)
        self.assertEqual(cliente.role, "cliente")
        self.assertEqual(cliente.token, "tok-b")
        self.assertEqual(cliente.whatsapp_id, "194")

    @override_settings(WHATSATENDE_TOKEN="tok-a", WHATSATENDE_WHATSAPP_ID="196")
    def test_whatsatende_cliente_sem_token_b_nao_fallback_para_a(self) -> None:
        provider = WhatsAtendeProvider(role="cliente")
        self.assertEqual(provider.role, "cliente")
        self.assertEqual(provider.token, "")
        self.assertEqual(provider.whatsapp_id, "")

    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        side_effect=["zapi", "evolution"],
    )
    def test_factory_atualiza_quando_provedor_muda(self, _mock_provider: object) -> None:
        clear_whatsapp_provider_cache()
        self.assertIsInstance(get_whatsapp_provider(), ZapiProvider)
        self.assertIsInstance(get_whatsapp_provider(), N8nOutboundProvider)


class TestWhatsAtendeProvider(SimpleTestCase):
    @override_settings(
        WHATSATENDE_API_URL="https://api.example.whatsatende",
        WHATSATENDE_TOKEN="token-conexao",
    )
    @patch("crm_app.services.whatsapp.whatsatende_provider.requests.request")
    def test_enviar_texto(self, mock_req) -> None:
        mock_resp = mock_req.return_value
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messageId": "X1", "status": "PENDING"}
        provider = WhatsAtendeProvider()
        ok, resp = provider.enviar_mensagem_texto_raw("31999882528", "Olá")
        self.assertTrue(ok)
        self.assertEqual(resp.get("messageId"), "X1")
        args = mock_req.call_args
        self.assertEqual(args.args[0], "POST")
        self.assertIn("/api/messages/send", args.args[1])
        self.assertEqual(args.kwargs["json"]["number"], "5531999882528")
        self.assertEqual(args.kwargs["json"]["body"], "Olá")

    @override_settings(WHATSATENDE_TOKEN="tok")
    def test_botoes_ainda_nao_suportados(self) -> None:
        provider = WhatsAtendeProvider()
        ok, _ = provider.enviar_mensagem_com_botoes_reply(
            "31999882528",
            "Confirma?",
            [{"id": "sim", "label": "SIM"}],
        )
        self.assertFalse(ok)

    @override_settings(
        WHATSATENDE_API_URL="https://api.example.whatsatende",
        WHATSATENDE_TOKEN="token-conexao",
    )
    @patch("crm_app.services.whatsapp.whatsatende_provider.requests.request")
    def test_check_number(self, mock_req) -> None:
        mock_resp = mock_req.return_value
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "existsInWhatsapp": True,
            "number": "5531999882528",
            "numberFormatted": "5531999882528@s.whatsapp.net",
        }
        provider = WhatsAtendeProvider()
        self.assertTrue(provider.verificar_numero_existe("31999882528"))


class TestN8nOutboundProvider(SimpleTestCase):
    @override_settings(
        N8N_OUTBOUND_WEBHOOK_URL="https://n8n.example/webhook/site-record-enviar-mensagem",
    )
    @patch("crm_app.services.whatsapp.n8n_outbound_provider.requests.post")
    def test_enviar_texto_via_n8n(self, mock_post) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {"ok": True}
        provider = N8nOutboundProvider()
        ok, resp = provider.enviar_mensagem_texto_raw("31999882528", "Olá")
        self.assertTrue(ok)
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["phone_number"], "5531999882528")
        self.assertEqual(payload["message_body"], "Olá")

    @override_settings(N8N_OUTBOUND_WEBHOOK_URL="")
    def test_texto_sem_webhook_falha(self) -> None:
        provider = N8nOutboundProvider()
        ok, err = provider.enviar_mensagem_texto_raw("31999882528", "Olá")
        self.assertFalse(ok)
        self.assertIn("N8N_OUTBOUND", str(err))

    @override_settings(
        N8N_OUTBOUND_WEBHOOK_URL="https://n8n.example/webhook/site-record-enviar-mensagem",
    )
    @patch("crm_app.services.whatsapp.n8n_outbound_provider.requests.post")
    def test_enviar_pdf_url_via_n8n(self, mock_post) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b""
        provider = N8nOutboundProvider()
        ok = provider.enviar_pdf_url(
            "31999882528",
            "https://cdn.example/doc.pdf",
            nome_arquivo="extrato.pdf",
            caption="Segue extrato",
        )
        self.assertTrue(ok)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["media_type"], "document")
        self.assertEqual(payload["media_url"], "https://cdn.example/doc.pdf")

    @override_settings(N8N_OUTBOUND_WEBHOOK_URL="https://n8n.example/webhook/x")
    @patch.object(EvolutionProvider, "enviar_imagem_b64", return_value={"messageId": "1"})
    def test_imagem_b64_delega_evolution(self, mock_b64) -> None:
        provider = N8nOutboundProvider()
        result = provider.enviar_imagem_b64("31999882528", "abc123", caption="img")
        self.assertEqual(result, {"messageId": "1"})
        mock_b64.assert_called_once()
