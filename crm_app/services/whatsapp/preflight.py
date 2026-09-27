"""Validação da configuração de envio do WhatsApp na subida dos workers."""
from __future__ import annotations

import logging
from typing import List

from django.conf import settings

logger = logging.getLogger(__name__)


def checar_config_outbound(origem: str) -> List[str]:
    """
    Retorna as variáveis de envio ausentes e registra CRITICAL quando houver alguma.

    Cada serviço Railway tem seu próprio conjunto de variáveis. Sem esse aviso na
    subida, um worker sem credencial executa a automação inteira e só falha na
    hora de responder ao cliente — o sintoma aparece como "não respondeu".
    """
    try:
        from crm_app.services.whatsapp_config_service import (
            get_active_whatsapp_provider_name,
        )

        provider = get_active_whatsapp_provider_name()
    except Exception as exc:
        logger.warning("[%s] Não foi possível resolver o provider ativo: %s", origem, exc)
        provider = "evolution"

    obrigatorias = {
        "evolution": ("EVOLUTION_API_URL", "EVOLUTION_API_KEY", "N8N_OUTBOUND_WEBHOOK_URL"),
        "zapi": ("ZAPI_INSTANCE_ID", "ZAPI_TOKEN", "ZAPI_CLIENT_TOKEN"),
    }.get(provider, ())

    faltando = [
        nome for nome in obrigatorias if not (getattr(settings, nome, "") or "")
    ]

    if faltando:
        logger.critical(
            "[%s] Configuração de envio incompleta para o provider '%s': %s ausente(s). "
            "As automações vão processar e falhar ao responder.",
            origem,
            provider,
            ", ".join(faltando),
        )
    else:
        logger.info("[%s] Configuração de envio OK (provider=%s).", origem, provider)
    return faltando
