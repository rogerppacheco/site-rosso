from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0193_historico_envio_origem_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="cdoibloco",
            name="vtop_obra_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=32,
                null=True,
                verbose_name="ID obra V.top",
            ),
        ),
        migrations.AddField(
            model_name="cdoibloco",
            name="vtop_etapa",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="Etapa V.top após última sync",
            ),
        ),
        migrations.AddField(
            model_name="cdoibloco",
            name="vtop_sincronizado_em",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Última sync V.top",
            ),
        ),
    ]
