from django.db import migrations, models


def marcar_diretoria_como_destinatario(apps, schema_editor):
    Usuario = apps.get_model("usuarios", "Usuario")
    Usuario.objects.filter(
        groups__name="Diretoria",
        is_active=True,
    ).update(recebe_selfie_presenca=True)


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0030_usuario_autorizar_historico_pap"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="recebe_selfie_presenca",
            field=models.BooleanField(
                default=False,
                help_text="Envia a foto de confirmação diária do módulo Presença para o WhatsApp 1 deste usuário.",
                verbose_name="Recebe selfie de presença no WhatsApp?",
            ),
        ),
        migrations.RunPython(
            marcar_diretoria_como_destinatario,
            migrations.RunPython.noop,
        ),
    ]
