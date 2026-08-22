from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0159_plano_valores_comissao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='planovalorescomissao',
            name='propagar_faixas',
            field=models.BooleanField(
                default=False,
                help_text='Atualiza colunas da banda em Regras por Faixa (COMISSÃO).',
            ),
        ),
    ]
