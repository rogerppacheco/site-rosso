from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0026_usuario_vendedor_solo"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="recebe_adiantamento_cnpj",
            field=models.BooleanField(
                default=True,
                help_text="Se desmarcado, o usuário não pode receber lançamento do tipo Adiantamento CNPJ.",
                verbose_name="Recebe adiantamento de CNPJ?",
            ),
        ),
    ]
