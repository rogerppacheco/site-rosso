from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("presenca", "0007_remove_confirmacaopresencadia_presenca_confirmacaopresencadia_data_supervisor_uniq_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="LogLembretePresencaSupervisor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data", models.DateField(db_index=True)),
                ("slot", models.CharField(
                    choices=[
                        ("10h", "Lembrete 10h"),
                        ("11h", "Lembrete 11h"),
                        ("12h_falta", "Falta automática 12h"),
                    ],
                    max_length=20,
                )),
                ("sucesso", models.BooleanField(default=False)),
                ("detalhe", models.CharField(blank=True, default="", max_length=500)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("supervisor", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="logs_lembrete_presenca",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "verbose_name": "Log lembrete presença supervisor",
                "verbose_name_plural": "Logs lembretes presença supervisor",
                "ordering": ["-criado_em"],
                "unique_together": {("data", "slot", "supervisor")},
            },
        ),
    ]
