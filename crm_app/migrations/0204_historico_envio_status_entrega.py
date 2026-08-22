# wamid + status de entrega (aceite da API vs falha posterior da Meta)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0203_nio_reagendamento_esteira"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicoenvioqualidade",
            name="erro_codigo",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Código Meta (ex.: 131048 spam, 131047 janela 24h)",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="historicoenvioqualidade",
            name="message_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "wamid / messageId retornado no aceite do envio "
                    "(correlação com webhook da Meta)"
                ),
                max_length=191,
            ),
        ),
        migrations.AddField(
            model_name="historicoenvioqualidade",
            name="status_atualizado_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="historicoenvioqualidade",
            name="status_entrega",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ACEITO", "Aceito pela API"),
                    ("ENVIADO", "Enviado"),
                    ("ENTREGUE", "Entregue"),
                    ("LIDO", "Lido"),
                    ("FALHOU", "Falha de entrega"),
                ],
                default="",
                help_text=(
                    "ACEITO = HTTP 200 da API; "
                    "ENVIADO/ENTREGUE/LIDO/FALHOU = webhook posterior"
                ),
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="historicoenvioqualidade",
            index=models.Index(fields=["message_id"], name="crm_app_his_msgid_idx"),
        ),
    ]
