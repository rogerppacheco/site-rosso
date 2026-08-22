from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0170_estatistica_bot_cdoe_andamento'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='biometria_aprovada',
            field=models.BooleanField(
                blank=True,
                db_index=True,
                default=None,
                help_text=(
                    'True=Doc. Apto para Venda no Br Pronto; False=consultada sem aprovação; '
                    'null=ainda não consultada.'
                ),
                null=True,
                verbose_name='Biometria aprovada',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='biometria_consultada_em',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Data/hora consulta biometria',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='biometria_data_apta',
            field=models.CharField(
                blank=True,
                help_text='Data do Doc. Apto mais recente retornada pelo Br Pronto.',
                max_length=50,
                null=True,
                verbose_name='Data biometria apta',
            ),
        ),
    ]
