from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0117_historicoconsultaautomacaopap"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicoconsultaautomacaopap",
            name="atualizado_em",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="historicoconsultaautomacaopap",
            name="mensagem_resultado",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Resumo do resultado/erro retornado ao usuário.",
            ),
        ),
        migrations.AddField(
            model_name="historicoconsultaautomacaopap",
            name="status_execucao",
            field=models.CharField(
                choices=[
                    ("pendente", "Pendente"),
                    ("sucesso", "Sucesso"),
                    ("erro", "Erro"),
                ],
                db_index=True,
                default="pendente",
                help_text="Resultado final da consulta após execução da automação.",
                max_length=20,
            ),
        ),
    ]
