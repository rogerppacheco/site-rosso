from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0198_destinos_operacionais_multiplos'),
    ]

    operations = [
        migrations.AddField(
            model_name='esteiravendasconfig',
            name='relatorio_pendencia_cliente_ativo',
            field=models.BooleanField(
                default=False,
                help_text='Envia imagem com volume de pendências tipo CLIENTE por vendedor (seg–sex).',
                verbose_name='Relatório pendências CLIENTE (WPP)',
            ),
        ),
        migrations.AddField(
            model_name='esteiravendasconfig',
            name='relatorio_pendencia_cliente_horario_1',
            field=models.TimeField(
                default='12:00',
                verbose_name='Horário 1º envio (pend. cliente)',
            ),
        ),
        migrations.AddField(
            model_name='esteiravendasconfig',
            name='relatorio_pendencia_cliente_horario_2',
            field=models.TimeField(
                default='18:00',
                verbose_name='Horário 2º envio (pend. cliente)',
            ),
        ),
        migrations.AddField(
            model_name='esteiravendasconfig',
            name='relatorio_pendencia_cliente_controle_disparos',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Controle interno para evitar reenvio no mesmo slot diário.',
            ),
        ),
        migrations.AddField(
            model_name='esteiravendasconfig',
            name='relatorio_pendencia_cliente_grupos',
            field=models.ManyToManyField(
                blank=True,
                help_text='Grupos que recebem a imagem de pendências CLIENTE por vendedor.',
                related_name='+',
                to='crm_app.grupodisparo',
                verbose_name='Grupos WhatsApp (pend. cliente)',
            ),
        ),
    ]
