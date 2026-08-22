from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0140_historico_atendimento_ia_cliente'),
    ]

    operations = [
        migrations.AddField(
            model_name='recordapoia',
            name='url_externa',
            field=models.TextField(
                blank=True,
                null=True,
                help_text='URL de backup (OneDrive) quando o arquivo local não está disponível',
            ),
        ),
    ]
