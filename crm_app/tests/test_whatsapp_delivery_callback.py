from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from crm_app.services.whatsapp.delivery_tracker import (
    aguardar_entrega,
    processar_delivery_callback,
    processar_message_status_callback,
)
from crm_app.services.whatsapp.status_entrega_service import (
    extrair_erro_meta,
    extrair_message_id_resposta,
    mapear_status_entrega,
)
from crm_app.services.whatsapp.zapi_provider import ZapiProvider
from crm_app.whatsapp_webhook_fastpath import avaliar_fastpath_zapi
from crm_app.whatsapp_webhook_normalizer import extrair_callbacks_status, normalizar_webhook

_LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "wa-delivery-tests",
    }
}


@override_settings(CACHES=_LOCMEM)
class DeliveryTrackerTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_callback_sucesso_sem_error(self) -> None:
        out = processar_delivery_callback(
            {
                "type": "DeliveryCallback",
                "phone": "5531999999999",
                "messageId": "MID1",
                "zaapId": "ZAAP1",
            }
        )
        self.assertTrue(out["ok"])
        ok, detalhe = aguardar_entrega("MID1", timeout=0.5)
        self.assertTrue(ok)
        self.assertIsNotNone(detalhe)

    def test_callback_falha_com_error(self) -> None:
        processar_delivery_callback(
            {
                "type": "DeliveryCallback",
                "phone": "5531999999999",
                "messageId": "MID2",
                "zaapId": "ZAAP2",
                "error": "Phone number does not exist",
                "errorCode": "SHADOW_BAN",
            }
        )
        ok, detalhe = aguardar_entrega("ZAAP2", timeout=0.5)
        self.assertFalse(ok)
        self.assertEqual(detalhe["error"], "Phone number does not exist")

    def test_message_status_sent_confirma(self) -> None:
        out = processar_message_status_callback(
            {
                "type": "MessageStatusCallback",
                "status": "SENT",
                "ids": ["MID_STATUS"],
                "phone": "553188832369",
            }
        )
        self.assertTrue(out["ok"])
        ok, detalhe = aguardar_entrega("MID_STATUS", timeout=0.5)
        self.assertTrue(ok)
        self.assertEqual(detalhe["source"], "MessageStatus:SENT")

    def test_timeout_sem_callback(self) -> None:
        with patch(
            "crm_app.services.whatsapp.delivery_tracker._POLL_INTERVAL",
            0.05,
        ):
            ok, detalhe = aguardar_entrega("MID_INEXISTENTE", timeout=0.2)
        self.assertFalse(ok)
        self.assertIsNone(detalhe)

    def test_fastpath_ainda_ignora_delivery_se_chegar_la(self) -> None:
        """Defesa: se o view não interceptar, fastpath não enfileira handler pesado."""
        out = avaliar_fastpath_zapi(
            {
                "type": "DeliveryCallback",
                "phone": "5531999999999",
                "messageId": "MID3",
            }
        )
        self.assertIsNotNone(out)
        self.assertIn("ignorado", out["mensagem"].lower())


class ResolverDestinoZapiTests(SimpleTestCase):
    def test_usa_telefone_canonico_sem_nono_digito(self) -> None:
        provider = ZapiProvider()
        provider.instance_id = "x"
        provider.token = "y"
        with patch.object(
            provider,
            "consultar_phone_exists",
            return_value={
                "exists": True,
                "phone": "553188832369",
                "lid": "210848551301251@lid",
            },
        ):
            destino = provider.resolver_destino_envio("31988832369")
        self.assertEqual(destino, "553188832369")

    def test_grupo_nao_consulta_phone_exists(self) -> None:
        provider = ZapiProvider()
        mock_consulta = MagicMock()
        provider.consultar_phone_exists = mock_consulta  # type: ignore[method-assign]
        destino = provider.resolver_destino_envio("120363019502650977-group")
        self.assertEqual(destino, "120363019502650977-group")
        mock_consulta.assert_not_called()


class StatusEntregaMetaTests(SimpleTestCase):
    def test_extrai_wamid_da_resposta_send(self) -> None:
        self.assertEqual(
            extrair_message_id_resposta({"messageId": "wamid.ABC"}),
            "wamid.ABC",
        )
        self.assertEqual(
            extrair_message_id_resposta({"data": {"id": "wamid.NEST"}}),
            "wamid.NEST",
        )

    def test_codigo_spam_131048(self) -> None:
        code, msg = extrair_erro_meta(
            {
                "errors": [
                    {
                        "code": 131048,
                        "title": "Spam Rate Limit Hit",
                        "message": "Too many previous messages were blocked.",
                    }
                ]
            }
        )
        self.assertEqual(code, "131048")
        self.assertIn("spam", msg.lower())

    def test_mapear_falha(self) -> None:
        self.assertEqual(
            mapear_status_entrega(ok=False, error_code="131048"),
            "FALHOU",
        )
        self.assertEqual(
            mapear_status_entrega(ok=True, wa_status="READ"),
            "LIDO",
        )

    def test_webhook_meta_failed_131048(self) -> None:
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.SPAM1",
                                        "status": "failed",
                                        "recipient_id": "5531988782662",
                                        "errors": [
                                            {
                                                "code": 131048,
                                                "title": "Spam Rate Limit Hit",
                                                "error_data": {
                                                    "details": (
                                                        "Message failed to send because "
                                                        "there are restrictions on how "
                                                        "many messages can be sent."
                                                    )
                                                },
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        eventos = extrair_callbacks_status(payload)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["type"], "DeliveryCallback")
        self.assertEqual(eventos[0]["messageId"], "wamid.SPAM1")
        self.assertEqual(str(eventos[0]["errorCode"]), "131048")

    def test_webhook_whatsatende_message_failed(self) -> None:
        eventos = extrair_callbacks_status(
            {
                "event": "message.failed",
                "id": "wamid.WA1",
                "senderNumber": "5531988782662",
                "errorCode": 131047,
                "error": "Re-engagement message",
            }
        )
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["errorCode"], "131047")
        self.assertIn("Re-engagement", eventos[0]["error"])

    def test_ticket_open_nao_vira_status(self) -> None:
        payload = {
            "id": "wamid.X",
            "type": "text",
            "message": "oi",
            "senderNumber": "5531999882528",
            "ticketId": 1,
            "status": "open",
            "userId": None,
        }
        self.assertEqual(extrair_callbacks_status(payload), [])
        canon = normalizar_webhook(payload)
        self.assertEqual(canon["type"], "ReceivedCallback")
