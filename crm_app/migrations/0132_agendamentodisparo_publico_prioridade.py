from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0131_pagamentocomissaoitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='agendamentodisparo',
            name='prioridade',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Ordem de envio: menor número envia primeiro.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='agendamentodisparo',
            name='status_destinatarios',
            field=models.CharField(
                choices=[
                    ('somente_ativos', 'Somente ativos'),
                    ('somente_inativos', 'Somente inativos'),
                    ('todos', 'Todos'),
                ],
                default='somente_ativos',
                help_text='Define se a regra envia para usuários ativos, inativos ou todos.',
                max_length=20,
            ),
        ),
    ]
