# Origem (AUTO/MANUAL) e template Meta no histórico de envios Qualidade

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0192_qualidade_historico_canais"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicoenvioqualidade",
            name="origem",
            field=models.CharField(
                blank=True,
                choices=[
                    ("AUTO", "Automático"),
                    ("MANUAL", "Manual"),
                    ("SISTEMA", "Sistema"),
                ],
                default="MANUAL",
                help_text="AUTO = job 10:00; MANUAL = tela Qualidade; SISTEMA = webhook/botões",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="historicoenvioqualidade",
            name="template_nome",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Nome do template Meta quando canal WhatsApp usa template",
                max_length=120,
            ),
        ),
        migrations.AddIndex(
            model_name="historicoenvioqualidade",
            index=models.Index(
                fields=["-criado_em", "canal", "origem"],
                name="crm_app_his_criado_canal_idx",
            ),
        ),
    ]
