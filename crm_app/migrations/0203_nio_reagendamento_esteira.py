from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0202_sem_slot_email_gc'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='nio_reagendamento_em',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Reagendamento Nio (data/hora)'),
        ),
        migrations.AddField(
            model_name='venda',
            name='nio_reagendamento_msg',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='Reagendamento Nio (mensagem)'),
        ),
        migrations.AddField(
            model_name='venda',
            name='nio_reagendamento_status',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Último resultado da automação WhatsApp Nio (7029).',
                max_length=32,
                verbose_name='Reagendamento Nio (status)',
            ),
        ),
        migrations.CreateModel(
            name='NioReagendamentoExecucao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('modo', models.CharField(choices=[('unitario', 'Unitário'), ('massa', 'Em massa')], db_index=True, max_length=16)),
                ('status', models.CharField(
                    choices=[
                        ('pendente', 'Pendente'),
                        ('em_andamento', 'Em andamento'),
                        ('concluido', 'Concluído'),
                        ('interrompido', 'Interrompido'),
                        ('erro', 'Erro'),
                    ],
                    db_index=True,
                    default='pendente',
                    max_length=20,
                )),
                ('iniciado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                ('total_pedidos', models.PositiveIntegerField(default=0)),
                ('processados', models.PositiveIntegerField(default=0)),
                ('sucessos', models.PositiveIntegerField(default=0)),
                ('falhas', models.PositiveIntegerField(default=0)),
                ('cancelar_solicitado', models.BooleanField(default=False)),
                ('relatorio_json', models.JSONField(blank=True, default=dict)),
                ('mensagem_erro', models.TextField(blank=True, default='')),
                ('iniciado_por', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='nio_reagendamento_iniciados',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Reagendamento Nio (execução)',
                'verbose_name_plural': 'Reagendamento Nio (execuções)',
                'db_table': 'crm_nio_reagendamento_execucao',
                'ordering': ['-iniciado_em'],
            },
        ),
        migrations.CreateModel(
            name='NioReagendamentoItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('pendente', 'Pendente'),
                        ('em_andamento', 'Em andamento'),
                        ('sucesso', 'Sucesso'),
                        ('sem_slot', 'Sem slot'),
                        ('erro_cpf', 'Erro CPF'),
                        ('erro_consulta', 'Consulta indisponível'),
                        ('erro', 'Erro'),
                        ('cancelado', 'Cancelado'),
                    ],
                    db_index=True,
                    default='pendente',
                    max_length=20,
                )),
                ('mensagem', models.CharField(blank=True, default='', max_length=500)),
                ('dados_json', models.JSONField(blank=True, default=dict)),
                ('iniciado_em', models.DateTimeField(blank=True, null=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                ('execucao', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='itens',
                    to='crm_app.nioreagendamentoexecucao',
                )),
                ('venda', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='nio_reagendamento_itens',
                    to='crm_app.venda',
                )),
            ],
            options={
                'verbose_name': 'Reagendamento Nio (item)',
                'verbose_name_plural': 'Reagendamento Nio (itens)',
                'db_table': 'crm_nio_reagendamento_item',
                'ordering': ['id'],
            },
        ),
        migrations.AddIndex(
            model_name='nioreagendamentoitem',
            index=models.Index(fields=['execucao', 'status'], name='crm_nio_re_exec_status_idx'),
        ),
        migrations.AddIndex(
            model_name='nioreagendamentoitem',
            index=models.Index(fields=['venda', '-finalizado_em'], name='crm_nio_re_venda_fin_idx'),
        ),
    ]
