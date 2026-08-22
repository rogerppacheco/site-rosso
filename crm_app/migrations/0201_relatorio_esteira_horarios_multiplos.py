from django.db import migrations, models


def copiar_horarios_legado(apps, schema_editor):
    AnteciparInstalacaoConfig = apps.get_model('crm_app', 'AnteciparInstalacaoConfig')
    for config in AnteciparInstalacaoConfig.objects.all():
        slots: list[str] = []
        for horario in (config.relatorio_esteira_horario_1, config.relatorio_esteira_horario_2):
            if not horario:
                continue
            slot = f'{horario.hour:02d}:{horario.minute:02d}'
            if slot not in slots:
                slots.append(slot)
        config.relatorio_esteira_horarios = slots
        config.save(update_fields=['relatorio_esteira_horarios'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0200_lista_agendamento_vendedor'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_horarios',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Lista de horários HH:MM para disparo do relatório (seg–sex). Quantos forem necessários.',
                verbose_name='Horários do relatório esteira (GC)',
            ),
        ),
        migrations.AlterField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_horario_1',
            field=models.TimeField(
                default='17:20',
                help_text='Campo legado. Preferir relatorio_esteira_horarios.',
                verbose_name='Horário 1º envio (esteira GC)',
            ),
        ),
        migrations.AlterField(
            model_name='anteciparinstalacaoconfig',
            name='relatorio_esteira_horario_2',
            field=models.TimeField(
                default='18:00',
                help_text='Campo legado. Preferir relatorio_esteira_horarios.',
                verbose_name='Horário 2º envio (esteira GC)',
            ),
        ),
        migrations.RunPython(copiar_horarios_legado, noop_reverse),
    ]
