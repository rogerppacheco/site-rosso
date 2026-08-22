from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0135_antecipar_instalacao_nome_gc"),
    ]

    operations = [
        migrations.AddField(
            model_name="venda",
            name="bloquear_atualizacao_status_osab",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Quando marcado, a importação OSAB não atualiza este pedido "
                    "(exceto para INSTALADA, CANCELADA, INSTALADA OUTRO PDV e NÃO CONSTA NA OSAB)."
                ),
                verbose_name="Bloquear atualização de status pela OSAB",
            ),
        ),
    ]
