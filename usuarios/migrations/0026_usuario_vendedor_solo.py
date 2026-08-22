from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0025_add_valor_ajuda_custo_mensal"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="vendedor_solo",
            field=models.BooleanField(
                default=False,
                help_text="Permite ao vendedor acessar a ferramenta Presença para registrar a própria selfie/confirmar presença sem equipe.",
                verbose_name="Vendedor solo",
            ),
        ),
    ]
