"""Configuração singleton da esteira de vendas."""
from crm_app.models import EsteiraVendasConfig


def get_esteira_vendas_config() -> EsteiraVendasConfig:
    config = EsteiraVendasConfig.objects.first()
    if not config:
        config = EsteiraVendasConfig.objects.create(whatsapp_backoffice='')
    return config
