# Generated manually - Auditoria: qual automação está usando o BO

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0088_add_fila_espera_pap'),
    ]

    operations = [
        migrations.AddField(
            model_name='papboemuso',
            name='tipo_automacao',
            field=models.CharField(
                blank=True,
                choices=[
                    ('vender', 'Vender'),
                    ('credito', 'Crédito'),
                    ('pedido', 'Pedido'),
                    ('status', 'Status'),
                ],
                default='',
                help_text='Tipo de automação que está usando este login (para auditoria).',
                max_length=20,
                verbose_name='Tipo automação'
            ),
        ),
    ]
