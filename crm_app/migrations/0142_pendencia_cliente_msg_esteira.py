# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0141_recordapoia_url_externa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PendenciaClienteMsgEnviada',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telefone', models.CharField(max_length=20)),
                ('mensagem', models.TextField()),
                ('sucesso', models.BooleanField(default=False)),
                ('erro', models.CharField(blank=True, default='', max_length=500)),
                ('enviado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    'motivo_pendencia',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='msgs_cliente_enviadas',
                        to='crm_app.motivopendencia',
                    ),
                ),
                (
                    'usuario',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='msgs_pendencia_cliente_registradas',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'venda',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='msgs_pendencia_cliente_enviadas',
                        to='crm_app.venda',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Msg pendência cliente (enviada)',
                'verbose_name_plural': 'Msgs pendência cliente (enviadas)',
                'db_table': 'crm_pendencia_cliente_msg_enviada',
                'ordering': ['-enviado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='pendenciaclientemsgenviada',
            index=models.Index(fields=['venda', 'motivo_pendencia', 'sucesso'], name='crm_pend_cl_msg_v_m_s_idx'),
        ),
        migrations.AlterField(
            model_name='vendaesteiraevento',
            name='tipo_evento',
            field=models.CharField(
                choices=[
                    ('STATUS_ESTEIRA', 'Status esteira'),
                    ('MOTIVO_PENDENCIA', 'Motivo pendência'),
                    ('AGENDAMENTO', 'Agendamento'),
                    ('INSTALACAO', 'Instalação (OSAB)'),
                    ('INSTALACAO_FISICA', 'Instalação física'),
                    ('MSG_CLIENTE_PENDENCIA', 'WhatsApp cliente (pendência)'),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='historicoatendimentoiacliente',
            name='origem',
            field=models.CharField(
                choices=[
                    ('WEBHOOK', 'WhatsApp (contato externo)'),
                    ('BOAS_VINDAS', 'Boas-vindas'),
                    ('LEMBRETE_INSTALACAO', 'Lembrete instalação'),
                    ('PENDENCIA_CLIENTE', 'Pendência cliente (esteira)'),
                ],
                db_index=True,
                default='WEBHOOK',
                max_length=30,
            ),
        ),
    ]
