# Generated manually — Fase 2 Gestão Aproveitamento

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0138_pendencia_indevida'),
    ]

    operations = [
        migrations.CreateModel(
            name='VendaEsteiraEvento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo_evento', models.CharField(
                    choices=[
                        ('STATUS_ESTEIRA', 'Status esteira'),
                        ('MOTIVO_PENDENCIA', 'Motivo pendência'),
                        ('AGENDAMENTO', 'Agendamento'),
                        ('INSTALACAO', 'Instalação (OSAB)'),
                        ('INSTALACAO_FISICA', 'Instalação física'),
                    ],
                    db_index=True,
                    max_length=32,
                )),
                ('valor_anterior', models.CharField(blank=True, default='', max_length=500)),
                ('valor_novo', models.CharField(blank=True, default='', max_length=500)),
                ('origem', models.CharField(
                    choices=[
                        ('MANUAL', 'Manual (esteira)'),
                        ('OSAB', 'Importação OSAB'),
                        ('SISTEMA', 'Sistema'),
                    ],
                    db_index=True,
                    max_length=16,
                )),
                ('criado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('motivo_pendencia', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='eventos_esteira',
                    to='crm_app.motivopendencia',
                )),
                ('usuario', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='eventos_esteira_registrados',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('venda', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='eventos_esteira',
                    to='crm_app.venda',
                )),
            ],
            options={
                'verbose_name': 'Evento esteira',
                'verbose_name_plural': 'Eventos esteira',
                'db_table': 'crm_venda_esteira_evento',
                'ordering': ['criado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='vendaesteiraevento',
            index=models.Index(fields=['venda', 'tipo_evento', 'criado_em'], name='crm_venda_e_venda_i_8a1f2d_idx'),
        ),
        migrations.AddIndex(
            model_name='vendaesteiraevento',
            index=models.Index(fields=['tipo_evento', 'criado_em'], name='crm_venda_e_tipo_ev_4c9b1e_idx'),
        ),
    ]
