from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0029_brpronto_pool_bio"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="autorizar_historico_pap",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Se marcado (perfil Diretoria + matrícula/senha PAP), este login entra no pool "
                    "usado pelo Funil para buscar o histórico PAP. Enquanto estiver em uso, outro "
                    "usuário só consegue buscar se houver outro Diretoria disponível no pool."
                ),
                verbose_name="Autorizar busca do histórico PAP (Funil)",
            ),
        ),
    ]
