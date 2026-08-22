from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0128_agendamentodisparo_modo_especifico"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="venda",
            name="adiantamento_cnpj_realizado_em",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Adiantamento CNPJ realizado em"
            ),
        ),
        migrations.AddField(
            model_name="venda",
            name="adiantamento_cnpj_realizado_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="vendas_adiantamento_cnpj_realizado",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Adiantamento CNPJ realizado por",
            ),
        ),
    ]
