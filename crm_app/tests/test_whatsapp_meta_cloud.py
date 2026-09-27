"""Cloud API Meta: provider, factory, webhook GET/HMAC e normalização inbound."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from crm_app.services.whatsapp.factory import (
    PURPOSE_CLIENTE,
    clear_whatsapp_provider_cache,
    get_whatsapp_provider,
)
from crm_app.services.whatsapp.meta_cloud_provider import MetaCloudProvider
from crm_app.services.whatsapp.meta_webhook import (
    responder_verificacao_webhook_meta,
    validar_assinatura_meta,
)
from crm_app.services.whatsapp.zapi_provider import ZapiProvider
from crm_app.whatsapp_webhook_normalizer import (
    detectar_provedor,
    normalizar_webhook,
    payload_tem_mensagens_inbound_meta,
)


def _payload_texto_meta(texto: str = "oi") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "552136051000",
                                "phone_number_id": "123456",
                            },
                            "contacts": [{"wa_id": "5531999882528", "profile": {"name": "A"}}],
                            "messages": [
                                {
                                    "from": "5531999882528",
                                    "id": "wamid.IN1",
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class TestMetaNormalizer(SimpleTestCase):
    def test_detecta_cloud_api(self) -> None:
        self.assertEqual(detectar_provedor(_payload_texto_meta()), "meta")

    def test_normaliza_texto(self) -> None:
        canon = normalizar_webhook(_payload_texto_meta("VENDER"))
        self.assertEqual(canon["phone"], "5531999882528")
        self.assertEqual(canon["message"]["text"], "VENDER")
        self.assertEqual(canon["messageId"], "wamid.IN1")
        self.assertFalse(canon["fromMe"])
        self.assertEqual(canon["type"], "ReceivedCallback")

    def test_normaliza_botao_interactive(self) -> None:
        payload = _payload_texto_meta()
        payload["entry"][0]["changes"][0]["value"]["messages"] = [
            {
                "from": "5531999882528",
                "id": "wamid.BTN1",
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "pap_confirmar_sim", "title": "SIM"},
                },
            }
        ]
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["buttonsResponseMessage"]["buttonId"], "pap_confirmar_sim")
        self.assertEqual(canon["message"]["text"], "SIM")

    def test_normaliza_quick_reply_template(self) -> None:
        payload = _payload_texto_meta()
        payload["entry"][0]["changes"][0]["value"]["messages"] = [
            {
                "from": "5531999882528",
                "id": "wamid.QR1",
                "type": "button",
                "button": {"text": "CORRETO", "payload": "CORRETO"},
            }
        ]
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["buttonsResponseMessage"]["buttonId"], "CORRETO")
        self.assertEqual(canon["message"]["text"], "CORRETO")

    def test_payload_misto_tem_mensagem(self) -> None:
        payload = _payload_texto_meta()
        payload["entry"][0]["changes"].append(
            {
                "field": "messages",
                "value": {
                    "statuses": [
                        {"id": "wamid.OUT1", "status": "delivered", "recipient_id": "5531999882528"}
                    ]
                },
            }
        )
        self.assertTrue(payload_tem_mensagens_inbound_meta(payload))

    def test_status_only_nao_tem_mensagem(self) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "sent"}]}}]}],
        }
        self.assertFalse(payload_tem_mensagens_inbound_meta(payload))


class TestMetaWebhookHandshake(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    @override_settings(META_CLOUD_VERIFY_TOKEN="segredo-meta")
    def test_get_challenge_ok(self) -> None:
        req = self.factory.get(
            "/api/crm/webhook-whatsapp/",
            {"hub.mode": "subscribe", "hub.verify_token": "segredo-meta", "hub.challenge": "12345"},
        )
        resp = responder_verificacao_webhook_meta(req)
        self.assertIsInstance(resp, HttpResponse)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode(), "12345")

    @override_settings(META_CLOUD_VERIFY_TOKEN="segredo-meta")
    def test_get_challenge_token_errado(self) -> None:
        req = self.factory.get(
            "/api/crm/webhook-whatsapp/",
            {"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"},
        )
        resp = responder_verificacao_webhook_meta(req)
        self.assertEqual(resp.status_code, 403)

    def test_get_sem_hub_retorna_none(self) -> None:
        req = self.factory.get("/api/crm/webhook-whatsapp/")
        self.assertIsNone(responder_verificacao_webhook_meta(req))

    @override_settings(META_CLOUD_VERIFY_TOKEN="segredo-meta")
    def test_view_get_challenge(self) -> None:
        from rest_framework.test import APIRequestFactory

        from crm_app.views import WebhookWhatsAppView

        req = APIRequestFactory().get(
            "/api/crm/webhook-whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "segredo-meta",
                "hub.challenge": "abc",
            },
        )
        resp = WebhookWhatsAppView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode(), "abc")

    @override_settings(META_APP_SECRET="app-secret")
    def test_hmac_valido(self) -> None:
        payload = _payload_texto_meta()
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sig = hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
        req = self.factory.post(
            "/api/crm/webhook-whatsapp/",
            data=raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=f"sha256={sig}",
        )
        ok, err = validar_assinatura_meta(req, payload)
        self.assertTrue(ok)
        self.assertIsNone(err)

    @override_settings(META_APP_SECRET="app-secret")
    def test_hmac_ausente_rejeita(self) -> None:
        payload = _payload_texto_meta()
        req = self.factory.post(
            "/api/crm/webhook-whatsapp/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        ok, err = validar_assinatura_meta(req, payload)
        self.assertFalse(ok)
        self.assertIn("ausente", (err or "").lower())

    @override_settings(META_APP_SECRET="app-secret")
    def test_hmac_pulado_se_token_whatsatende(self) -> None:
        payload = _payload_texto_meta()
        req = self.factory.post("/api/crm/webhook-whatsapp/tok/", content_type="application/json")
        ok, err = validar_assinatura_meta(req, payload, path_token_validado=True)
        self.assertTrue(ok)
        self.assertIsNone(err)


class TestMetaFactory(SimpleTestCase):
    def tearDown(self) -> None:
        clear_whatsapp_provider_cache()

    @override_settings(
        META_CLOUD_ACCESS_TOKEN="tok",
        META_CLOUD_PHONE_NUMBER_ID="999",
        ZAPI_INSTANCE_ID="inst",
        ZAPI_TOKEN="z-tok",
    )
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="meta",
    )
    def test_factory_meta_cliente_graph_interno_zapi(self, _mock: object) -> None:
        clear_whatsapp_provider_cache()
        interno = get_whatsapp_provider()
        cliente = get_whatsapp_provider(purpose=PURPOSE_CLIENTE)
        self.assertIsInstance(interno, ZapiProvider)
        self.assertIsInstance(cliente, MetaCloudProvider)
        self.assertEqual(cliente.phone_number_id, "999")

    @override_settings(
        ZAPI_INSTANCE_ID="inst",
        ZAPI_TOKEN="z-tok",
        WHATSATENDE_TOKEN_B="tok-b",
        WHATSATENDE_WHATSAPP_ID_B="194",
        META_CLOUD_ACCESS_TOKEN="mtok",
        META_CLOUD_PHONE_NUMBER_ID="888",
    )
    @patch(
        "crm_app.services.whatsapp_config_service.get_active_whatsapp_provider_name",
        return_value="hybrid",
    )
    def test_hybrid_usa_meta_quando_credenciais_ok(self, _mock: object) -> None:
        clear_whatsapp_provider_cache()
        cliente = get_whatsapp_provider(purpose=PURPOSE_CLIENTE)
        self.assertIsInstance(cliente, MetaCloudProvider)


class TestMetaCloudProviderSend(SimpleTestCase):
    @override_settings(
        META_CLOUD_ACCESS_TOKEN="tok",
        META_CLOUD_PHONE_NUMBER_ID="555",
        META_CLOUD_API_VERSION="v21.0",
    )
    @patch("crm_app.services.whatsapp.meta_cloud_provider.requests.post")
    def test_enviar_texto(self, mock_post: MagicMock) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "messages": [{"id": "wamid.OUT"}]
        }
        ok, resp = MetaCloudProvider().enviar_mensagem_texto_raw("31999999999", "oi")
        self.assertTrue(ok)
        self.assertEqual(resp["messageId"], "wamid.OUT")
        args, kwargs = mock_post.call_args
        self.assertIn("/555/messages", args[0])
        self.assertEqual(kwargs["json"]["to"], "5531999999999")
        self.assertEqual(kwargs["json"]["type"], "text")

    @override_settings(
        META_CLOUD_ACCESS_TOKEN="tok",
        META_CLOUD_PHONE_NUMBER_ID="555",
    )
    @patch("crm_app.services.whatsapp.meta_cloud_provider.requests.post")
    def test_enviar_template(self, mock_post: MagicMock) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"messages": [{"id": "wamid.TPL"}]}
        ok, resp = MetaCloudProvider().enviar_template(
            "31988887777",
            "nio_boas_vindas_v1",
            body_params=["Bom dia", "Ana"],
        )
        self.assertTrue(ok)
        self.assertEqual(resp["messageId"], "wamid.TPL")
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["type"], "template")
        self.assertEqual(body["template"]["name"], "nio_boas_vindas_v1")
        params = body["template"]["components"][0]["parameters"]
        self.assertEqual([p["text"] for p in params], ["Bom dia", "Ana"])
