from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0115_add_data_instalacao_fisica"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditoriaLigacao",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provedor", models.CharField(choices=[("ZENVIA", "Zenvia Voice API")], default="ZENVIA", max_length=30)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("INICIADA", "Iniciada"),
                            ("PROCESSANDO", "Processando"),
                            ("FINALIZADA", "Finalizada"),
                            ("ARQUIVADA", "Arquivada"),
                            ("ERRO", "Erro"),
                        ],
                        db_index=True,
                        default="INICIADA",
                        max_length=20,
                    ),
                ),
                ("provider_call_id", models.CharField(db_index=True, max_length=120)),
                ("provider_recording_id", models.CharField(blank=True, db_index=True, max_length=120, null=True)),
                ("numero_origem", models.CharField(blank=True, max_length=20, null=True)),
                ("numero_destino", models.CharField(blank=True, max_length=20, null=True)),
                ("duracao_segundos", models.PositiveIntegerField(default=0)),
                ("consentimento_declarado", models.BooleanField(default=True)),
                ("consentimento_observacao", models.CharField(blank=True, max_length=255, null=True)),
                ("link_gravacao_provedor", models.TextField(blank=True, null=True)),
                ("link_gravacao_onedrive", models.TextField(blank=True, null=True)),
                ("expira_em", models.DateTimeField(blank=True, null=True)),
                ("payload_inicio", models.JSONField(blank=True, default=dict)),
                ("payload_webhook", models.JSONField(blank=True, default=dict)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("finalizado_em", models.DateTimeField(blank=True, null=True)),
                (
                    "auditor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ligacoes_auditoria_realizadas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "venda",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="auditoria_ligacoes",
                        to="crm_app.venda",
                    ),
                ),
            ],
            options={
                "verbose_name": "Auditoria Ligação",
                "verbose_name_plural": "Auditoria Ligações",
                "db_table": "crm_auditoria_ligacao",
                "ordering": ["-criado_em"],
            },
        ),
    ]

