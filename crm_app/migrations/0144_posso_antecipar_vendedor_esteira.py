from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0143_esteira_vendas_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='data_resposta_posso_antecipar',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Data/hora resposta posso antecipar'),
        ),
        migrations.AddField(
            model_name='venda',
            name='data_solicitacao_posso_antecipar',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Data/hora solicitação posso antecipar'),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_obs_posso_antecipar',
            field=models.TextField(
                blank=True,
                help_text='Texto extra além de Sim/Não e turno.',
                null=True,
                verbose_name='Observação vendedor (posso antecipar)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_pode_antecipar',
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text='True=Sim; False=Não; null=ainda não respondeu ou resposta não identificada.',
                null=True,
                verbose_name='Vendedor pode antecipar?',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_pode_antecipar_turno',
            field=models.CharField(
                blank=True,
                choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
                max_length=10,
                null=True,
                verbose_name='Turno antecipação (vendedor)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_resposta_posso_antecipar',
            field=models.TextField(
                blank=True,
                help_text='Texto completo recebido do vendedor.',
                null=True,
                verbose_name='Resposta vendedor (posso antecipar)',
            ),
        ),
        migrations.CreateModel(
            name='PossoAnteciparVendedorEnviado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telefone', models.CharField(db_index=True, help_text='WhatsApp do vendedor (dígitos normalizados)', max_length=20)),
                ('data_envio', models.DateTimeField(auto_now_add=True)),
                ('respondido_em', models.DateTimeField(blank=True, null=True)),
                (
                    'solicitado_por',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='posso_antecipar_solicitados',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'venda',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='posso_antecipar_enviados',
                        to='crm_app.venda',
                    ),
                ),
                (
                    'vendedor',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='posso_antecipar_enviados',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Posso antecipar enviado ao vendedor',
                'verbose_name_plural': 'Posso antecipar enviados ao vendedor',
                'db_table': 'crm_posso_antecipar_vendedor_enviado',
                'ordering': ['-data_envio'],
            },
        ),
    ]
