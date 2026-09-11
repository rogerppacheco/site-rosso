from __future__ import annotations

from django.test import TestCase, override_settings

from crm_app.models import WhatsAppIntegracaoConfig
from crm_app.services.whatsapp_config_service import (
    canal_cliente_pronto,
    update_whatsapp_config,
)


class TestCanalClienteMeta(TestCase):
    def setUp(self) -> None:
        WhatsAppIntegracaoConfig.load()

    @override_settings(WHATSATENDE_TOKEN_B="", WHATSATENDE_WHATSAPP_ID_B="")
    def test_sem_token_b_nunca_pronto(self) -> None:
        cfg = WhatsAppIntegracaoConfig.load()
        cfg.envios_cliente_ativos = True
        cfg.save(update_fields=["envios_cliente_ativos"])
        self.assertFalse(canal_cliente_pronto())

    @override_settings(WHATSATENDE_TOKEN_B="tok-b", WHATSATENDE_WHATSAPP_ID_B="194")
    def test_token_b_exige_interruptor(self) -> None:
        cfg = WhatsAppIntegracaoConfig.load()
        cfg.envios_cliente_ativos = False
        cfg.save(update_fields=["envios_cliente_ativos"])
        self.assertFalse(canal_cliente_pronto())
        cfg.envios_cliente_ativos = True
        cfg.save(update_fields=["envios_cliente_ativos"])
        self.assertTrue(canal_cliente_pronto())

    @override_settings(WHATSATENDE_TOKEN_B="", WHATSATENDE_WHATSAPP_ID_B="")
    def test_nao_ativa_sem_credencial_meta(self) -> None:
        with self.assertRaises(ValueError):
            update_whatsapp_config(user=None, envios_cliente_ativos=True)

    @override_settings(
        WHATSATENDE_TOKEN_B="tok-b",
        WHATSATENDE_WHATSAPP_ID_B="194",
        ZAPI_INSTANCE_ID="inst",
        ZAPI_TOKEN="z-tok",
    )
    def test_labels_e_hibrido_ao_liberar(self) -> None:
        cfg = WhatsAppIntegracaoConfig.load()
        cfg.provider = WhatsAppIntegracaoConfig.PROVIDER_ZAPI
        cfg.envios_cliente_ativos = False
        cfg.save(update_fields=["provider", "envios_cliente_ativos"])
        update_whatsapp_config(
            user=None,
            envios_cliente_ativos=True,
            numero_equipe_label="31999990000",
            numero_cliente_label="2136051000",
        )
        cfg.refresh_from_db()
        self.assertTrue(cfg.envios_cliente_ativos)
        self.assertEqual(cfg.provider, WhatsAppIntegracaoConfig.PROVIDER_HYBRID)
        self.assertEqual(cfg.numero_equipe_label, "31999990000")
        self.assertEqual(cfg.numero_cliente_label, "2136051000")
