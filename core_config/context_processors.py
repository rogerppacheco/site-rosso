"""Context processors para templates públicos da Futura Telecom."""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest


def site_branding(request: HttpRequest) -> dict[str, Any]:
    """Expõe contatos e marca no template (alterar só no settings/.env)."""
    phone_display = getattr(settings, "SITE_PHONE_DISPLAY", "(31) 9XXXX-XXXX")
    whatsapp_digits = getattr(settings, "SITE_WHATSAPP_DIGITS", "319XXXXXXXX")
    email = getattr(settings, "SITE_CONTACT_EMAIL", "contato@futuratelecom.com.br")
    brand = getattr(settings, "SITE_BRAND_NAME", "Futura Telecom")
    brand_parts = brand.split(None, 1)
    return {
        "SITE_BRAND_NAME": brand,
        "SITE_BRAND_LINE_1": brand_parts[0] if brand_parts else brand,
        "SITE_BRAND_LINE_2": brand_parts[1] if len(brand_parts) > 1 else "",
        "SITE_PHONE_DISPLAY": phone_display,
        "SITE_WHATSAPP_DIGITS": whatsapp_digits,
        "SITE_CONTACT_EMAIL": email,
        "SITE_WHATSAPP_URL": f"https://wa.me/{whatsapp_digits}",
    }


def planos_landing(request: HttpRequest) -> dict[str, Any]:
    """
    Planos públicos a partir da importação GDP vigente.

    Query string opcional: ?cidade=Belo Horizonte&uf=MG
    Fallback: SITE_LANDING_CIDADE / SITE_LANDING_UF no settings.
    """
    from crm_app.services.gdp_preco_service import listar_planos_landing
    from urllib.parse import quote

    cidade = (request.GET.get("cidade") or getattr(settings, "SITE_LANDING_CIDADE", "") or "").strip()
    uf = (request.GET.get("uf") or getattr(settings, "SITE_LANDING_UF", "") or "").strip()
    cod_ibge = (request.GET.get("ibge") or "").strip()

    payload = listar_planos_landing(cidade=cidade, uf=uf, cod_ibge=cod_ibge)
    for plano in payload.get("planos", []):
        plano["whatsapp_url"] = (
            f"https://wa.me/{getattr(settings, 'SITE_WHATSAPP_DIGITS', '319XXXXXXXX')}"
            f"?text={quote(plano.get('whatsapp_texto', ''))}"
        )

    return {
        "PLANOS_LANDING": payload.get("planos", []),
        "PLANOS_LANDING_META": {
            "origem": payload.get("origem"),
            "escopo": payload.get("escopo"),
            "cidade": payload.get("cidade"),
            "uf": payload.get("uf"),
            "gdp_disponivel": payload.get("gdp_disponivel", False),
        },
    }
