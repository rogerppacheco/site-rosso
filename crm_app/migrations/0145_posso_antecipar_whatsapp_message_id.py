from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0144_posso_antecipar_vendedor_esteira'),
    ]

    operations = [
        migrations.AddField(
            model_name='possoanteciparvendedorenviado',
            name='whatsapp_message_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='messageId Z-API da mensagem com botões (para identificar clique no reenvio).',
                max_length=128,
            ),
        ),
    ]
