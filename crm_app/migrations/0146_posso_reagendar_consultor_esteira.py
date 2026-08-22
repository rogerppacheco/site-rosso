from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0145_posso_antecipar_whatsapp_message_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='consultor_pode_reagendar',
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text='True=Sim reagendar; False=Não; null=sem resposta.',
                null=True,
                verbose_name='Consultor pode reagendar?',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='consultor_reagendar_data',
            field=models.DateField(blank=True, null=True, verbose_name='Data sugerida reagendamento (consultor)'),
        ),
        migrations.AddField(
            model_name='venda',
            name='consultor_reagendar_turno',
            field=models.CharField(
                blank=True,
                choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
                max_length=10,
                null=True,
                verbose_name='Turno sugerido reagendamento (consultor)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='consultor_reagendar_resposta',
            field=models.TextField(
                blank=True,
                help_text='Resumo da consulta posso reagendar.',
                null=True,
                verbose_name='Resposta consultor (posso reagendar)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='data_resposta_reagendar_consultor',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Data/hora resposta reagendar consultor'),
        ),
        migrations.AddField(
            model_name='venda',
            name='data_solicitacao_reagendar_consultor',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Data/hora solicitação reagendar consultor'),
        ),
        migrations.CreateModel(
            name='PossoReagendarConsultorSessao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telefone', models.CharField(db_index=True, help_text='WhatsApp do consultor/vendedor', max_length=20)),
                (
                    'etapa',
                    models.CharField(
                        choices=[
                            ('SIM_NAO', 'Aguardando Sim/Não'),
                            ('DATA', 'Aguardando data'),
                            ('TURNO', 'Aguardando turno'),
                            ('CONCLUIDO', 'Concluído'),
                            ('RECUSADO', 'Recusado'),
                        ],
                        db_index=True,
                        default='SIM_NAO',
                        max_length=16,
                    ),
                ),
                ('whatsapp_message_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('datas_opcoes_json', models.CharField(blank=True, default='', help_text='JSON com 3 datas ISO', max_length=128)),
                ('data_escolhida', models.DateField(blank=True, null=True)),
                (
                    'periodo_escolhido',
                    models.CharField(
                        blank=True,
                        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
                        max_length=10,
                        null=True,
                    ),
                ),
                ('pode_reagendar', models.BooleanField(blank=True, null=True)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                (
                    'solicitado_por',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='reagendar_consultor_solicitados',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'venda',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='reagendar_consultor_sessoes',
                        to='crm_app.venda',
                    ),
                ),
                (
                    'vendedor',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='reagendar_consultor_sessoes',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Sessão posso reagendar consultor',
                'verbose_name_plural': 'Sessões posso reagendar consultor',
                'db_table': 'crm_posso_reagendar_consultor_sessao',
                'ordering': ['-criado_em'],
            },
        ),
    ]
