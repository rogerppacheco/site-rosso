from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0154_pap_job_fila'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_gc_ativo',
            field=models.BooleanField(
                default=False,
                help_text='Envia ao GC o volume de ativados e esteira de auditoria (seg-sex).',
                verbose_name='Relatório diário esteira (GC)',
            ),
        ),
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_horario_1',
            field=models.TimeField(default='17:20', verbose_name='Horário 1º envio (esteira GC)'),
        ),
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_horario_2',
            field=models.TimeField(default='18:00', verbose_name='Horário 2º envio (esteira GC)'),
        ),
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_controle_disparos',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Controle interno para evitar reenvio no mesmo slot diário.',
            ),
        ),
    ]
