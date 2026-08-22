# Generated manually — canais LIGACAO/RESPOSTA + índice histórico Qualidade

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0191_whatsapp_provider_hybrid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicoenvioqualidade",
            name="canal",
            field=models.CharField(
                choices=[
                    ("WHATSAPP", "WhatsApp"),
                    ("EMAIL", "E-mail"),
                    ("LIGACAO", "Ligação"),
                    ("RESPOSTA", "Resposta do cliente"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="historicoenvioqualidade",
            index=models.Index(
                fields=["contrato", "canal", "-criado_em"],
                name="crm_app_his_contrat_canal_idx",
            ),
        ),
    ]
