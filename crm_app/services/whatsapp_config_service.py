"""Resolução do provedor WhatsApp ativo (banco + variáveis de ambiente)."""
from __future__ import annotations

import os
from typing import Any, Dict

from django.conf import settings

from crm_app.models import WhatsAppIntegracaoConfig

_PROVIDERS_VALIDOS = frozenset(
    {
        WhatsAppIntegracaoConfig.PROVIDER_ZAPI,
        WhatsAppIntegracaoConfig.PROVIDER_EVOLUTION,
        WhatsAppIntegracaoConfig.PROVIDER_WHATSATENDE,
        WhatsAppIntegracaoConfig.PROVIDER_HYBRID,
    }
)

_PROVIDERS_CLIENTE_CLOUD = frozenset(
    {
        WhatsAppIntegracaoConfig.PROVIDER_WHATSATENDE,
        WhatsAppIntegracaoConfig.PROVIDER_HYBRID,
    }
)


def get_active_whatsapp_provider_name() -> str:
    """Provedor efetivo: registro único no banco; fallback para env/settings."""
    try:
        cfg = WhatsAppIntegracaoConfig.load()
        provider = (cfg.provider or "").strip().lower()
        if provider in _PROVIDERS_VALIDOS:
            return provider
    except Exception:
        pass
    fallback = (
        getattr(settings, "WHATSAPP_PROVIDER", None)
        or os.environ.get("WHATSAPP_PROVIDER", "zapi")
        or "zapi"
    )
    return str(fallback).strip().lower()


def cliente_usa_cloud_api() -> bool:
    """True quando envios a cliente final passam pela WhatsAtende (Número B)."""
    return get_active_whatsapp_provider_name() in _PROVIDERS_CLIENTE_CLOUD


def clear_whatsapp_provider_cache() -> None:
    from crm_app.services.whatsapp.factory import clear_whatsapp_provider_cache as _clear

    _clear()


def _credenciais_zapi_ok() -> bool:
    return bool(
        getattr(settings, "ZAPI_INSTANCE_ID", "")
        and getattr(settings, "ZAPI_TOKEN", "")
    )


def _credenciais_evolution_ok() -> bool:
    return bool(
        getattr(settings, "EVOLUTION_API_URL", "")
        and getattr(settings, "EVOLUTION_API_KEY", "")
    )


def _credenciais_whatsatende_ok() -> bool:
    return bool((getattr(settings, "WHATSATENDE_TOKEN", "") or "").strip())


def _credenciais_whatsatende_conexao_ok() -> bool:
    """Token + ID da conexão A — necessários para QR/status/disconnect."""
    return _credenciais_whatsatende_ok() and bool(
        (getattr(settings, "WHATSATENDE_WHATSAPP_ID", "") or "").strip()
    )


def _credenciais_whatsatende_cliente_ok() -> bool:
    """Número B (oficial) — envios a cliente final."""
    return bool((getattr(settings, "WHATSATENDE_TOKEN_B", "") or "").strip()) and bool(
        (getattr(settings, "WHATSATENDE_WHATSAPP_ID_B", "") or "").strip()
    )


def _credenciais_n8n_ok() -> bool:
    for key in ("N8N_OUTBOUND_WEBHOOK_URL", "N8N_WEBHOOK_URL", "OUTBOUND_WEBHOOK_URL"):
        val = getattr(settings, key, None) or os.environ.get(key, "")
        if val and str(val).strip():
            return True
    return False


def _validar_credenciais_provedor(provider: str) -> None:
    """Garante pré-requisitos mínimos antes de ativar o modo."""
    if provider == WhatsAppIntegracaoConfig.PROVIDER_HYBRID:
        faltando = []
        if not _credenciais_zapi_ok():
            faltando.append("Z-API (ZAPI_INSTANCE_ID / ZAPI_TOKEN)")
        if not _credenciais_whatsatende_cliente_ok():
            faltando.append(
                "WhatsAtende B (WHATSATENDE_TOKEN_B / WHATSATENDE_WHATSAPP_ID_B)"
            )
        if faltando:
            raise ValueError(
                "Modo híbrido exige credenciais de: " + "; ".join(faltando)
            )
    elif provider == WhatsAppIntegracaoConfig.PROVIDER_WHATSATENDE:
        if not _credenciais_whatsatende_ok() and not _credenciais_whatsatende_cliente_ok():
            raise ValueError(
                "WhatsAtende exige WHATSATENDE_TOKEN (A) e/ou TOKEN_B (cliente)."
            )
    elif provider == WhatsAppIntegracaoConfig.PROVIDER_ZAPI:
        if not _credenciais_zapi_ok():
            raise ValueError("Z-API exige ZAPI_INSTANCE_ID e ZAPI_TOKEN no servidor.")
    elif provider == WhatsAppIntegracaoConfig.PROVIDER_EVOLUTION:
        if not _credenciais_evolution_ok():
            raise ValueError("Evolution exige EVOLUTION_API_URL e EVOLUTION_API_KEY.")


def build_whatsapp_config_payload() -> Dict[str, Any]:
    env_default = (
        getattr(settings, "WHATSAPP_PROVIDER", None)
        or os.environ.get("WHATSAPP_PROVIDER", "zapi")
        or "zapi"
    ).strip().lower()
    cfg = None
    provider = env_default
    atualizado_em = None
    atualizado_por = None
    db_indisponivel = False

    try:
        from django.db import close_old_connections

        close_old_connections()
        cfg = WhatsAppIntegracaoConfig.load()
        provider = get_active_whatsapp_provider_name()
        atualizado_em = cfg.atualizado_em.isoformat() if cfg.atualizado_em else None
        if cfg.atualizado_por_id:
            atualizado_por = (
                cfg.atualizado_por.get_full_name() or cfg.atualizado_por.username
            )
    except Exception:
        db_indisponivel = True

    payload: Dict[str, Any] = {
        "provider": provider,
        "providerLabel": dict(WhatsAppIntegracaoConfig.PROVIDER_CHOICES).get(
            provider, provider
        ),
        "instanceName": getattr(settings, "EVOLUTION_INSTANCE_NAME", "site_record_zap"),
        "whatsatendeWhatsappId": getattr(settings, "WHATSATENDE_WHATSAPP_ID", "") or "",
        "whatsatendeWhatsappIdB": getattr(settings, "WHATSATENDE_WHATSAPP_ID_B", "") or "",
        "whatsatendeApiUrl": getattr(
            settings, "WHATSATENDE_API_URL", "https://api.app14.whatsatende.com.br"
        ),
        "zapiConfigured": _credenciais_zapi_ok(),
        "evolutionConfigured": _credenciais_evolution_ok(),
        "whatsatendeConfigured": _credenciais_whatsatende_ok(),
        "whatsatendeConnectionConfigured": _credenciais_whatsatende_conexao_ok(),
        "whatsatendeClienteConfigured": _credenciais_whatsatende_cliente_ok(),
        "whatsatendeWebhookTokenConfigured": bool(
            (getattr(settings, "WHATSATENDE_WEBHOOK_TOKEN", "") or "").strip()
        ),
        "hybridReady": _credenciais_zapi_ok() and _credenciais_whatsatende_cliente_ok(),
        "n8nConfigured": _credenciais_n8n_ok(),
        "envDefaultProvider": env_default,
        "atualizadoEm": atualizado_em,
        "atualizadoPor": atualizado_por,
        "mapaHybrid": {
            "interno": "zapi",
            "cliente": "whatsatende_b",
        },
    }
    try:
        from crm_app.services.whatsapp.webhook_token import (
            montar_url_webhook_whatsatende,
        )

        payload["whatsatendeWebhookUrl"] = montar_url_webhook_whatsatende()
    except Exception:
        payload["whatsatendeWebhookUrl"] = (
            f"{getattr(settings, 'SITE_URL', 'https://www.recordpap.com.br').rstrip('/')}"
            "/api/crm/webhook-whatsapp/"
        )
    if db_indisponivel:
        payload["dbIndisponivel"] = True
        payload["aviso"] = (
            "Banco temporariamente indisponível — exibindo último provedor conhecido "
            "ou padrão do servidor. Tente salvar novamente em instantes."
        )
    return payload


def set_whatsapp_provider(provider: str, user) -> WhatsAppIntegracaoConfig:
    normalized = (provider or "").strip().lower()
    if normalized not in _PROVIDERS_VALIDOS:
        raise ValueError(f"Provedor inválido: {provider}")
    _validar_credenciais_provedor(normalized)
    cfg = WhatsAppIntegracaoConfig.load()
    cfg.provider = normalized
    cfg.atualizado_por = user
    cfg.save(update_fields=["provider", "atualizado_por", "atualizado_em"])
    clear_whatsapp_provider_cache()
    return cfg
