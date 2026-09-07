from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0206_historicopapbusca_login_pap'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='pedido_pap',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True, unique=True, verbose_name='Pedido PAP'),
        ),
        migrations.AddField(
            model_name='venda',
            name='valor_plano_pap',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='Valor Mensal PAP'),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_matricula_pap',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='Matrícula Vendedor PAP'),
        ),
    ]
