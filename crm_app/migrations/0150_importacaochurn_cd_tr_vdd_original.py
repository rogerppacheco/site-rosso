from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0149_logimportacaoosab_reversao'),
    ]

    operations = [
        migrations.AddField(
            model_name='importacaochurn',
            name='cd_tr_vdd_original',
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
                verbose_name='CD TR VDD original (planilha churn)',
            ),
        ),
    ]
