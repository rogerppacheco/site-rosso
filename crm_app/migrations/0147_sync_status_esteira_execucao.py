# Generated manually for SyncStatusEsteiraExecucao

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0146_posso_reagendar_consultor_esteira'),
    ]

    operations = [
        migrations.CreateModel(
            name='SyncStatusEsteiraExecucao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('modo', models.CharField(choices=[('automatico', 'Automático'), ('manual', 'Manual')], db_index=True, max_length=16)),
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
                ('atualizados', models.PositiveIntegerField(default=0)),
                ('sem_alteracao', models.PositiveIntegerField(default=0)),
                ('erros', models.PositiveIntegerField(default=0)),
                ('ignorados_sem_cpf', models.PositiveIntegerField(default=0)),
                ('relatorio_json', models.JSONField(blank=True, default=dict)),
                ('mensagem_erro', models.TextField(blank=True, default='')),
                ('iniciado_por', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sync_status_esteira_iniciados',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Sync status esteira (PAP)',
                'verbose_name_plural': 'Sync status esteira (PAP)',
                'db_table': 'crm_sync_status_esteira_execucao',
                'ordering': ['-iniciado_em'],
            },
        ),
    ]
