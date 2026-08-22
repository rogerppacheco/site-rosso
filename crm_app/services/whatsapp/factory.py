"""Factory do provider WhatsApp (zapi | evolution | whatsatende | hybrid)."""
from __future__ import annotations

from typing import Dict, Tuple

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.n8n_outbound_provider import N8nOutboundProvider
from crm_app.services.whatsapp.whatsatende_provider import WhatsAtendeProvider
from crm_app.services.whatsapp.zapi_provider import ZapiProvider

PURPOSE_INTERNO = "interno"
PURPOSE_CLIENTE = "cliente"

_cached_providers: Dict[Tuple[str, str, str], WhatsAppProvider] = {}


def clear_whatsapp_provider_cache() -> None:
    """Invalida cache in-process (ex.: após salvar provedor na mesma réplica)."""
    _cached_providers.clear()


def resolve_backend_for_purpose(provider_name: str, purpose: str) -> Tuple[str, str]:
    """
    Mapeia (provedor global, purpose) → (backend efetivo, role WhatsAtende).

    hybrid: interno → Z-API; cliente → WhatsAtende Número B.
    whatsatende: dual A/B na mesma plataforma.
    zapi/evolution: um backend só (ignoram purpose).
    """
    name = (provider_name or "").strip().lower()
    role = (
        PURPOSE_CLIENTE
        if (purpose or "").strip().lower() == PURPOSE_CLIENTE
        else PURPOSE_INTERNO
    )
    if name == "hybrid":
        if role == PURPOSE_CLIENTE:
            return "whatsatende", PURPOSE_CLIENTE
        return "zapi", PURPOSE_INTERNO
    if name == "whatsatende":
        return "whatsatende", role
    if name == "evolution":
        return "evolution", PURPOSE_INTERNO
    return "zapi", PURPOSE_INTERNO


def get_whatsapp_provider(purpose: str = PURPOSE_INTERNO) -> WhatsAppProvider:
    """
    Resolve o provider efetivo consultando o banco a cada chamada.

    purpose=interno → bot/equipe/grupos (Número A).
    purpose=cliente → cliente final / Cloud API (Número B).

    Modo hybrid: Z-API (interno) + WhatsAtende B (cliente).
    """
    from crm_app.services.whatsapp_config_service import get_active_whatsapp_provider_name

    provider_name = get_active_whatsapp_provider_name()
    backend, role = resolve_backend_for_purpose(provider_name, purpose)
    key = (provider_name, backend, role)
    cached = _cached_providers.get(key)
    if cached is not None:
        return cached

    if backend == "evolution":
        inst: WhatsAppProvider = N8nOutboundProvider()
    elif backend == "whatsatende":
        inst = WhatsAtendeProvider(role=role)
    else:
        inst = ZapiProvider()
    _cached_providers[key] = inst
    return inst
