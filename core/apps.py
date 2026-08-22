from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core' # nome do seu app

    def ready(self):
        import core.signals  # Importante: registra os signals