# Generated manually - Controle por automação PAP (vender, crédito, pedido, status)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0021_usuario_autorizar_inclusao_wpp'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='pap_automacao_vender',
            field=models.BooleanField(
                default=True,
                help_text='Se marcado, este login pode ser usado pela automação VENDER (nova venda pelo WhatsApp).',
                verbose_name='PAP: automação Vender'
            ),
        ),
        migrations.AddField(
            model_name='usuario',
            name='pap_automacao_credito',
            field=models.BooleanField(
                default=True,
                help_text='Se marcado, este login pode ser usado pela automação CRÉDITO (análise de crédito pelo WhatsApp).',
                verbose_name='PAP: automação Crédito'
            ),
        ),
        migrations.AddField(
            model_name='usuario',
            name='pap_automacao_pedido',
            field=models.BooleanField(
                default=True,
                help_text='Se marcado, este login pode ser usado pela automação PEDIDO (consulta de pedido/O.S. pelo WhatsApp).',
                verbose_name='PAP: automação Pedido'
            ),
        ),
        migrations.AddField(
            model_name='usuario',
            name='pap_automacao_status',
            field=models.BooleanField(
                default=True,
                help_text='Se marcado, este login pode ser usado pela automação STATUS (consulta online de pedido no PAP).',
                verbose_name='PAP: automação Status'
            ),
        ),
    ]
