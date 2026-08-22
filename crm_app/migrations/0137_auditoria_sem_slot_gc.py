# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0136_venda_bloquear_atualizacao_status_osab'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditoriaSemSlotGC',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ordem_servico', models.CharField(blank=True, max_length=50)),
                ('uf', models.CharField(blank=True, max_length=2)),
                ('endereco_completo', models.TextField(blank=True)),
                ('data_agendamento_cadastrada', models.DateField(blank=True, null=True)),
                ('turno_agendamento_cadastrado', models.CharField(blank=True, choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')], max_length=10)),
                ('data_desejada_cliente', models.DateField()),
                ('turno_desejado_cliente', models.CharField(choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')], max_length=10)),
                ('telefone_contato', models.CharField(blank=True, max_length=120)),
                ('imagem_anexo', models.ImageField(blank=True, null=True, upload_to='auditoria_sem_slot/%Y/%m/')),
                ('mensagem_enviada', models.TextField(blank=True)),
                ('enviado_gc', models.BooleanField(default=False)),
                ('enviados_diretoria', models.JSONField(blank=True, default=list)),
                ('erros', models.JSONField(blank=True, default=list)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('usuario', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auditorias_sem_slot', to=settings.AUTH_USER_MODEL)),
                ('venda', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auditorias_sem_slot', to='crm_app.venda')),
            ],
            options={
                'verbose_name': 'Auditoria Sem Slot (GC)',
                'verbose_name_plural': 'Auditorias Sem Slot (GC)',
                'ordering': ['-criado_em'],
            },
        ),
    ]
