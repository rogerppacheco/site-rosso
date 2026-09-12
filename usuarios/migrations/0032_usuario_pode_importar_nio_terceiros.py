from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0031_usuario_recebe_selfie_presenca"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="pode_importar_nio_terceiros",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Se marcado, o usuário pode sincronizar e importar colaboradores "
                    "da Gestão de Terceiros NIO na tela Gestão de Usuários."
                ),
                verbose_name="Pode importar NIO Terceiros?",
            ),
        ),
    ]
