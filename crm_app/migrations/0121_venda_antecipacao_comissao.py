# Generated manually for antecipacao_comissao

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0120_auditoria_ligacao_historico_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='antecipacao_comissao',
            field=models.BooleanField(
                default=False,
                help_text='Indica se a comissão desta venda foi antecipada (informação administrativa).',
                verbose_name='Antecipação de comissão',
            ),
        ),
    ]
