from django.conf import settings


def branding(request):
    return {
        "SITE_BRAND": getattr(settings, "SITE_BRAND", "BN"),
        "SITE_MODULE_PREFIX": getattr(settings, "SITE_MODULE_PREFIX", "BN"),
        "SITE_TEXT_LOGO": getattr(settings, "SITE_TEXT_LOGO", True),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
        "SITE_CONTACT_PHONE": getattr(settings, "SITE_CONTACT_PHONE", ""),
        "SITE_CONTACT_EMAIL": getattr(settings, "SITE_CONTACT_EMAIL", ""),
    }


# Injetado de site-clickup
def branding(request):
    return {
        "SITE_BRAND": getattr(settings, "SITE_BRAND", "Record PAP"),
        "SITE_MODULE_PREFIX": getattr(settings, "SITE_MODULE_PREFIX", "Record"),
        "SITE_TEXT_LOGO": getattr(settings, "SITE_TEXT_LOGO", False),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
        "SITE_CONTACT_PHONE": getattr(settings, "SITE_CONTACT_PHONE", ""),
        "SITE_CONTACT_EMAIL": getattr(settings, "SITE_CONTACT_EMAIL", ""),
    }
