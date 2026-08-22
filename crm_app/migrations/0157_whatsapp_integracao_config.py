from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0156_whatsapp_webhook_fila"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppIntegracaoConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("zapi", "Z-API (legado / plano B)"),
                            ("evolution", "Evolution + n8n (Opção B)"),
                        ],
                        default="zapi",
                        max_length=20,
                        verbose_name="Provedor ativo",
                    ),
                ),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                (
                    "atualizado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Config. integração WhatsApp",
                "verbose_name_plural": "Config. integração WhatsApp",
            },
        ),
    ]
