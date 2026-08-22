"""Testes do serviço de notificação Teams via n8n."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from crm_app.services.teams_notification_service import (
    TeamsNotificationService,
    media_url_absoluta,
)


class TeamsNotificationServiceTest(SimpleTestCase):
    @override_settings(N8N_TEAMS_WEBHOOK_URL="")
    def test_nao_configurado_sem_url(self) -> None:
        svc = TeamsNotificationService()
        self.assertFalse(svc.configurado)
        ok, err = svc.enviar_mensagem(titulo="T", texto="msg", source="test")
        self.assertFalse(ok)
        self.assertIn("N8N_TEAMS_WEBHOOK_URL", str(err))

    @override_settings(
        N8N_TEAMS_WEBHOOK_URL="https://n8n.example/webhook/site-record-teams-notificar",
        SITE_URL="https://www.recordpap.com.br",
        MEDIA_URL="/media/",
    )
    @patch("crm_app.services.teams_notification_service.requests.post")
    def test_envio_sucesso(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200, content=b"{}", json=lambda: {"ok": True})
        svc = TeamsNotificationService()
        ok, body = svc.enviar_mensagem(
            titulo="Sem SLOT — RJ",
            texto="Pedido 123",
            source="auditoria-sem-slot",
            image_url="https://example.com/img.jpg",
        )
        self.assertTrue(ok)
        self.assertEqual(body, {"ok": True})
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["title"], "Sem SLOT — RJ")
        self.assertEqual(payload["image_url"], "https://example.com/img.jpg")

    @override_settings(
        SITE_URL="https://www.recordpap.com.br",
        MEDIA_URL="/media/",
    )
    def test_media_url_absoluta(self) -> None:
        url = media_url_absoluta("auditoria_sem_slot/2026/07/print.jpg")
        self.assertEqual(
            url,
            "https://www.recordpap.com.br/media/auditoria_sem_slot/2026/07/print.jpg",
        )
