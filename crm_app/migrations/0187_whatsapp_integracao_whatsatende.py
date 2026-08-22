# Generated manually for WhatsAtende provider choice

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0186_analise_credito_resultado_modal"),
    ]

    operations = [
        migrations.AlterField(
            model_name="whatsappintegracaoconfig",
            name="provider",
            field=models.CharField(
                choices=[
                    ("zapi", "Z-API (legado / plano B)"),
                    ("evolution", "Evolution + n8n (Opção B)"),
                    ("whatsatende", "WhatsAtende"),
                ],
                default="zapi",
                max_length=20,
                verbose_name="Provedor ativo",
            ),
        ),
    ]
