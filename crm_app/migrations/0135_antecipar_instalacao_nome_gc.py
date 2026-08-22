from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0134_antecipar_instalacao_fisica_complemento'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='nome_gc',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Nome do GC'),
        ),
    ]
