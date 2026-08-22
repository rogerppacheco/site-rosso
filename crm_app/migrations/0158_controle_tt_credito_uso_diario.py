from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0157_whatsapp_integracao_config"),
    ]

    operations = [
        migrations.CreateModel(
            name="ControleTTCreditoUsoDiario",
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
                ("matricula_vendedor", models.CharField(db_index=True, max_length=50)),
                ("data", models.DateField(db_index=True)),
                ("consultas", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Controle TT uso crédito (dia)",
                "verbose_name_plural": "Controle TT uso crédito (dia)",
                "db_table": "crm_controle_tt_credito_uso_diario",
                "ordering": ["data", "matricula_vendedor"],
                "unique_together": {("matricula_vendedor", "data")},
            },
        ),
    ]
