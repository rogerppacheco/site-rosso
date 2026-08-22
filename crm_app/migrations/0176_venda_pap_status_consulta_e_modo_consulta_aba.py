from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0175_tempo_tratamento'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='pap_status_consultado_em',
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text='Última consulta de status no PAP (Esteira). Exibido na coluna Status Atual.',
                null=True,
                verbose_name='Consulta PAP (data/hora)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='pap_status_consultado_matricula',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Matrícula PAP usada na última consulta de status na Esteira.',
                max_length=50,
                verbose_name='Consulta PAP (matrícula)',
            ),
        ),
        migrations.AlterField(
            model_name='syncstatusesteiraexecucao',
            name='modo',
            field=models.CharField(
                choices=[
                    ('automatico', 'Automático'),
                    ('manual', 'Manual'),
                    ('consulta_aba', 'Consulta da aba'),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
