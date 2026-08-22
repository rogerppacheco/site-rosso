"""Testes do token de webhook WhatsAtende (path/query/header)."""
from __future__ import annotations

from django.test import RequestFactory, SimpleTestCase, override_settings

from crm_app.services.whatsapp.webhook_token import (
    montar_url_webhook_whatsatende,
    validar_token_webhook_whatsatende,
)


class TestWebhookTokenWhatsAtende(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def test_rota_sem_token_libera_legado(self) -> None:
        req = self.factory.post("/api/crm/webhook-whatsapp/")
        ok, err = validar_token_webhook_whatsatende(req, path_token=None)
        self.assertTrue(ok)
        self.assertIsNone(err)

    @override_settings(WHATSATENDE_WEBHOOK_TOKEN="segredo-forte")
    def test_path_token_valido(self) -> None:
        req = self.factory.post("/api/crm/webhook-whatsapp/segredo-forte/")
        ok, err = validar_token_webhook_whatsatende(req, path_token="segredo-forte")
        self.assertTrue(ok)
        self.assertIsNone(err)

    @override_settings(WHATSATENDE_WEBHOOK_TOKEN="segredo-forte")
    def test_path_token_invalido(self) -> None:
        req = self.factory.post("/api/crm/webhook-whatsapp/errado/")
        ok, err = validar_token_webhook_whatsatende(req, path_token="errado")
        self.assertFalse(ok)
        self.assertIn("inválido", err or "")

    @override_settings(WHATSATENDE_WEBHOOK_TOKEN="")
    def test_path_token_sem_config_no_servidor(self) -> None:
        req = self.factory.post("/api/crm/webhook-whatsapp/qualquer/")
        ok, err = validar_token_webhook_whatsatende(req, path_token="qualquer")
        self.assertFalse(ok)
        self.assertIn("não configurado", err or "")

    @override_settings(WHATSATENDE_WEBHOOK_TOKEN="segredo-forte")
    def test_query_token_valido(self) -> None:
        req = self.factory.post("/api/crm/webhook-whatsapp/?token=segredo-forte")
        ok, err = validar_token_webhook_whatsatende(req, path_token=None)
        self.assertTrue(ok)

    @override_settings(
        WHATSATENDE_WEBHOOK_TOKEN="abc123",
        SITE_URL="https://www.recordpap.com.br",
    )
    def test_montar_url_com_token(self) -> None:
        url = montar_url_webhook_whatsatende()
        self.assertEqual(
            url,
            "https://www.recordpap.com.br/api/crm/webhook-whatsapp/abc123/",
        )
