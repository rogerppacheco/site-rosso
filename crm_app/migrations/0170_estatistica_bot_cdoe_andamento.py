# Generated manually for CDOE / ANDAMENTO choices

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0169_brpronto_pool_bio'),
    ]

    operations = [
        migrations.AlterField(
            model_name='estatisticabotwhatsapp',
            name='comando',
            field=models.CharField(
                choices=[
                    ('FACHADA', 'Fachada'),
                    ('DFV', 'DFV (Power BI)'),
                    ('CDOE', 'CDOE (Power BI)'),
                    ('VIABILIDADE', 'Viabilidade'),
                    ('FATURA', 'Fatura'),
                    ('STATUS', 'Status'),
                    ('CREDITO', 'Crédito'),
                    ('BIO', 'Bio (Br Pronto)'),
                    ('PEDIDO', 'Pedido'),
                    ('VENDER', 'Vender'),
                    ('ANDAMENTO', 'Andamento'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
