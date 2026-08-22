# Generated for ConfirmacaoPresencaDia (selfie + OneDrive)

from django.conf import settings
from django.db import migrations, models
from django.db.models.deletion import CASCADE


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('presenca', '0005_presenca_presenca_pr_colabor_f3e223_idx'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfirmacaoPresencaDia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data', models.DateField(db_index=True)),
                ('foto_url', models.URLField(blank=True, max_length=500)),
                ('latitude', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=8, max_digits=12, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('supervisor', models.ForeignKey(on_delete=CASCADE, related_name='confirmacoes_presenca_dia', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Confirmação de presença (selfie do dia)',
                'verbose_name_plural': 'Confirmações de presença (selfies)',
                'ordering': ['-data', '-criado_em'],
            },
        ),
        migrations.AddConstraint(
            model_name='confirmacaopresencadia',
            constraint=models.UniqueConstraint(fields=('data', 'supervisor'), name='presenca_confirmacaopresencadia_data_supervisor_uniq'),
        ),
    ]
