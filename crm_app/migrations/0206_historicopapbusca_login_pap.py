from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm_app", "0205_historico_pap_pedido"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicopapbusca",
            name="login_pap",
            field=models.ForeignKey(
                blank=True,
                help_text="Login Diretoria do pool usado na sessão PAP.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="historico_pap_logins_usados",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
