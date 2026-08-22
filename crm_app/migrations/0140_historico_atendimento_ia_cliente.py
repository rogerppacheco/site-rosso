from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0139_venda_esteira_evento'),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoricoAtendimentoIACliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telefone', models.CharField(db_index=True, help_text='Telefone do cliente normalizado (apenas dígitos)', max_length=20)),
                ('mensagem_cliente', models.TextField(verbose_name='Mensagem do cliente')),
                ('resposta_sistema', models.TextField(verbose_name='Resposta enviada')),
                ('intencao', models.CharField(
                    choices=[
                        ('AGENDAMENTO', 'Agendamento'),
                        ('INSTALACAO', 'Instalação'),
                        ('STATUS', 'Status do pedido'),
                        ('OS', 'Ordem de serviço'),
                        ('HUMANO', 'Escalonar humano'),
                        ('OUTROS', 'Outros'),
                    ],
                    db_index=True,
                    default='OUTROS',
                    max_length=20,
                )),
                ('fonte_resposta', models.CharField(
                    choices=[
                        ('TEMPLATE', 'Template (dados do pedido)'),
                        ('IA', 'IA (Groq/Gemini)'),
                        ('FALLBACK', 'Fallback padrão'),
                    ],
                    default='TEMPLATE',
                    max_length=20,
                )),
                ('origem', models.CharField(
                    choices=[
                        ('WEBHOOK', 'WhatsApp (contato externo)'),
                        ('BOAS_VINDAS', 'Boas-vindas'),
                        ('LEMBRETE_INSTALACAO', 'Lembrete instalação'),
                    ],
                    db_index=True,
                    default='WEBHOOK',
                    max_length=30,
                )),
                ('avisos_bo_enviados', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Quantidade de destinos WhatsApp notificados nesta interação.',
                    verbose_name='Avisos enviados (BO/Diretoria)',
                )),
                ('criado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('venda', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='historico_atendimento_ia_cliente',
                    to='crm_app.venda',
                )),
            ],
            options={
                'verbose_name': 'Histórico atendimento IA (cliente)',
                'verbose_name_plural': 'Históricos atendimento IA (cliente)',
                'db_table': 'crm_historico_atendimento_ia_cliente',
                'ordering': ['-criado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='historicoatendimentoiacliente',
            index=models.Index(fields=['venda', '-criado_em'], name='crm_hist_ia_venda_idx'),
        ),
        migrations.AddIndex(
            model_name='historicoatendimentoiacliente',
            index=models.Index(fields=['telefone', '-criado_em'], name='crm_hist_ia_tel_idx'),
        ),
    ]
