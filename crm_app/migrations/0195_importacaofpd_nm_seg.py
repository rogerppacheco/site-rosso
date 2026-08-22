from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0194_cdoibloco_vtop_obra_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='importacaofpd',
            name='nm_seg',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Segmento do cliente na planilha (Varejo / Empresarial)',
                max_length=40,
            ),
        ),
    ]
