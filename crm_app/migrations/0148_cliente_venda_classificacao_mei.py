# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0147_sync_status_esteira_execucao'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='classificacao_mei',
            field=models.CharField(
                blank=True,
                choices=[
                    ('MEI', 'MEI'),
                    ('NMEI', 'Não MEI'),
                    ('INDETERMINADO', 'Indeterminado'),
                    ('CPF', 'CPF (não aplicável)'),
                ],
                db_index=True,
                help_text='MEI, NMEI (não MEI), INDETERMINADO ou CPF.',
                max_length=20,
                null=True,
                verbose_name='Classificação MEI',
            ),
        ),
        migrations.AddField(
            model_name='cliente',
            name='classificacao_mei_consultada_em',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Classificação MEI consultada em',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='classificacao_mei',
            field=models.CharField(
                blank=True,
                choices=[
                    ('MEI', 'MEI'),
                    ('NMEI', 'Não MEI'),
                    ('INDETERMINADO', 'Indeterminado'),
                    ('CPF', 'CPF (não aplicável)'),
                ],
                db_index=True,
                help_text='Snapshot MEI/NMEI no momento do cadastro da venda.',
                max_length=20,
                null=True,
                verbose_name='Classificação MEI na venda',
            ),
        ),
    ]
