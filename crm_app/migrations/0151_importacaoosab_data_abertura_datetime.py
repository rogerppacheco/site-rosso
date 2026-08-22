# Generated manually for OSAB data_abertura datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0150_importacaochurn_cd_tr_vdd_original"),
    ]

    operations = [
        migrations.AlterField(
            model_name="importacaoosab",
            name="data_abertura",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
