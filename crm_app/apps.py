from django.apps import AppConfig


class CrmAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'crm_app'

    def ready(self):
        # Importa os sinais quando o app estiver pronto para rodar
        import crm_app.signals
        import crm_app.signals_m10  # Novos signals para M-10 automático
        import crm_app.signals_m10_automacao  # Automação de M-10 com FPD
        import crm_app.pap_job_fila  # noqa: F401 — modelo PapJobFila
        import crm_app.whatsapp_webhook_fila  # noqa: F401 — modelo WhatsappWebhookFila
        import crm_app.services.whatsapp_ia_config_service  # noqa: F401 — invalidação cache blocklist

        # Scheduler em processo dedicado: python manage.py run_scheduler (ver Procfile).
