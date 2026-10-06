from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0212_plano_portfolio_mvno'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='QualidadeFocoTratamento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indicador', models.CharField(default='FPD', max_length=3)),
                ('segmento', models.CharField(blank=True, default='', max_length=32)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('usuario', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='qualidade_foco_tratamento',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Foco do tratamento Qualidade',
                'verbose_name_plural': 'Focos do tratamento Qualidade',
                'db_table': 'crm_qualidade_foco_tratamento',
            },
        ),
    ]
