from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0127_pap_protocolo_confirmacao_envio'),
    ]

    operations = [
        migrations.AddField(
            model_name='agendamentodisparo',
            name='controle_disparos',
            field=models.JSONField(blank=True, default=dict, help_text='Controle interno para evitar reenvio no mesmo slot diário.'),
        ),
        migrations.AddField(
            model_name='agendamentodisparo',
            name='dias_semana',
            field=models.JSONField(blank=True, default=list, help_text='Dias da semana permitidos (0=Seg ... 6=Dom), usado no modo específico semanal.'),
        ),
        migrations.AddField(
            model_name='agendamentodisparo',
            name='horarios_especificos',
            field=models.JSONField(blank=True, default=list, help_text='Lista de horários HH:MM para envio (08:00-22:00).'),
        ),
        migrations.AddField(
            model_name='agendamentodisparo',
            name='modo_envio',
            field=models.CharField(choices=[('INTERVALO', 'Intervalo'), ('ESPECIFICO', 'Horários específicos')], default='INTERVALO', help_text='INTERVALO usa intervalo/hora_fim. ESPECIFICO usa horários exatos.', max_length=20),
        ),
        migrations.AlterField(
            model_name='agendamentodisparo',
            name='hora_fim',
            field=models.PositiveSmallIntegerField(blank=True, default=19, help_text='Horário máximo (0-23) para envio na frequência diária. Ex: 19 = até 19h59.', null=True),
        ),
        migrations.AlterField(
            model_name='agendamentodisparo',
            name='intervalo_minutos',
            field=models.PositiveIntegerField(blank=True, default=60, help_text='Intervalo mínimo em minutos entre envios (ex: 60 = 1x por hora, 30 = a cada 30 min)', null=True),
        ),
    ]
