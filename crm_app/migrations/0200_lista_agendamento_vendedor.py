from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0199_esteira_relatorio_pendencia_cliente'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='vendedor_lista_agendamento_status',
            field=models.CharField(
                blank=True,
                choices=[('CIENTE', 'Estou ciente'), ('REAGENDAR', 'Solicitou reagendar')],
                db_index=True,
                help_text='Resposta do vendedor à lista diária (não altera o agendamento do CRM).',
                max_length=16,
                null=True,
                verbose_name='Status resposta lista agendamento',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_lista_reagendar_data',
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name='Data sugerida (lista agendamento)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_lista_reagendar_turno',
            field=models.CharField(
                blank=True,
                choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
                max_length=10,
                null=True,
                verbose_name='Turno sugerido (lista agendamento)',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='vendedor_lista_agendamento_resposta',
            field=models.TextField(
                blank=True,
                null=True,
                verbose_name='Resumo resposta lista agendamento',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='data_envio_lista_agendamento',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Data/hora envio lista agendamento',
            ),
        ),
        migrations.AddField(
            model_name='venda',
            name='data_resposta_lista_agendamento',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Data/hora resposta lista agendamento',
            ),
        ),
        migrations.CreateModel(
            name='ListaAgendamentoVendedorEnviado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telefone', models.CharField(db_index=True, help_text='WhatsApp do vendedor (dígitos)', max_length=20)),
                ('data_referencia', models.DateField(db_index=True, help_text='Dia dos agendamentos listados')),
                (
                    'periodo',
                    models.CharField(
                        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                (
                    'venda_ids_json',
                    models.TextField(
                        blank=True,
                        default='[]',
                        help_text='JSON com IDs das vendas incluídas no envio.',
                    ),
                ),
                (
                    'whatsapp_message_id',
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default='',
                        help_text='messageId Z-API da mensagem com botões iniciais.',
                        max_length=128,
                    ),
                ),
                ('data_envio', models.DateTimeField(auto_now_add=True)),
                ('respondido_em', models.DateTimeField(blank=True, null=True)),
                (
                    'vendedor',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='lista_agendamento_enviados',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Lista agendamento enviada ao vendedor',
                'verbose_name_plural': 'Listas agendamento enviadas ao vendedor',
                'db_table': 'crm_lista_agendamento_vendedor_enviado',
                'ordering': ['-data_envio'],
            },
        ),
        migrations.CreateModel(
            name='ListaAgendamentoVendedorSessao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telefone', models.CharField(db_index=True, max_length=20)),
                (
                    'etapa',
                    models.CharField(
                        choices=[
                            ('INICIAL', 'Aguardando ciência/reagendar'),
                            ('PEDIDO', 'Escolhendo pedido'),
                            ('DATA', 'Aguardando data'),
                            ('TURNO', 'Aguardando turno'),
                            ('CIENTE', 'Ciente'),
                            ('CONCLUIDO', 'Reagendar solicitado'),
                        ],
                        db_index=True,
                        default='INICIAL',
                        max_length=16,
                    ),
                ),
                (
                    'offset_pedidos',
                    models.PositiveIntegerField(default=0, help_text='Página atual na escolha de pedidos.'),
                ),
                ('whatsapp_message_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
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
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                (
                    'envio',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='sessoes',
                        to='crm_app.listaagendamentovendedorenviado',
                    ),
                ),
                (
                    'venda_escolhida',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='lista_agendamento_sessoes',
                        to='crm_app.venda',
                    ),
                ),
                (
                    'vendedor',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='lista_agendamento_sessoes',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Sessão lista agendamento vendedor',
                'verbose_name_plural': 'Sessões lista agendamento vendedor',
                'db_table': 'crm_lista_agendamento_vendedor_sessao',
                'ordering': ['-criado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='listaagendamentovendedorenviado',
            index=models.Index(
                fields=['data_referencia', 'periodo', 'vendedor'],
                name='crm_lista_a_data_re_7c2a1b_idx',
            ),
        ),
    ]
