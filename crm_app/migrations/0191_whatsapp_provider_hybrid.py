# Generated manually for hybrid WhatsApp provider

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0190_whatsapp_custo_oficial_boas_vindas"),
    ]

    operations = [
        migrations.AlterField(
            model_name="whatsappintegracaoconfig",
            name="provider",
            field=models.CharField(
                choices=[
                    ("zapi", "Z-API (legado / plano B)"),
                    ("evolution", "Evolution + n8n (Opção B)"),
                    ("whatsatende", "WhatsAtende (A+B)"),
                    (
                        "hybrid",
                        "Híbrido: Z-API (equipe) + WhatsAtende oficial (cliente)",
                    ),
                ],
                default="zapi",
                max_length=20,
                verbose_name="Provedor ativo",
            ),
        ),
    ]
