from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0213_qualidade_foco_tratamento"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MensagemWhatsAppAtendimento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "telefone",
                    models.CharField(
                        db_index=True,
                        help_text="Telefone normalizado, somente dígitos, sem DDI 55.",
                        max_length=20,
                    ),
                ),
                (
                    "direcao",
                    models.CharField(
                        choices=[("ENTRADA", "Recebida"), ("SAIDA", "Enviada")],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                (
                    "tipo",
                    models.CharField(
                        choices=[("SESSAO", "Sessão"), ("MODELO", "Modelo")],
                        default="SESSAO",
                        max_length=10,
                    ),
                ),
                ("texto", models.TextField(blank=True, default="")),
                ("template_name", models.CharField(blank=True, default="", max_length=120)),
                ("message_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("origem", models.CharField(blank=True, default="CRM", max_length=20)),
                ("sucesso", models.BooleanField(default=True)),
                ("erro", models.TextField(blank=True, default="")),
                ("data_hora", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                (
                    "enviado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mensagens_whatsapp_atendimento_enviadas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "venda",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mensagens_whatsapp_atendimento",
                        to="crm_app.venda",
                    ),
                ),
            ],
            options={
                "verbose_name": "Mensagem de atendimento WhatsApp",
                "verbose_name_plural": "Mensagens de atendimento WhatsApp",
                "db_table": "crm_mensagem_whatsapp_atendimento",
                "ordering": ["data_hora", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="mensagemwhatsappatendimento",
            index=models.Index(fields=["telefone", "-data_hora"], name="crm_wa_atend_tel_dt_idx"),
        ),
        migrations.AddIndex(
            model_name="mensagemwhatsappatendimento",
            index=models.Index(fields=["telefone", "direcao", "-data_hora"], name="crm_wa_atend_tel_dir_idx"),
        ),
        migrations.AddConstraint(
            model_name="mensagemwhatsappatendimento",
            constraint=models.UniqueConstraint(
                condition=models.Q(message_id="", _negated=True),
                fields=("message_id", "direcao"),
                name="uniq_wa_atend_msgid_dir",
            ),
        ),
    ]
