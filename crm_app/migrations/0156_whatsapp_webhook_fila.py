from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0155_antecipar_relatorio_esteira_gc'),
    ]

    operations = [
        migrations.CreateModel(
            name='WhatsappWebhookFila',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payload', models.JSONField(default=dict)),
                ('base_url', models.CharField(blank=True, default='', max_length=256)),
                ('status', models.CharField(choices=[('pendente', 'Pendente'), ('processando', 'Processando'), ('concluido', 'Concluído'), ('erro', 'Erro')], db_index=True, default='pendente', max_length=16)),
                ('prioridade', models.SmallIntegerField(db_index=True, default=5)),
                ('tentativas', models.PositiveSmallIntegerField(default=0)),
                ('max_tentativas', models.PositiveSmallIntegerField(default=2)),
                ('erro', models.TextField(blank=True, default='')),
                ('criado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('iniciado_em', models.DateTimeField(blank=True, null=True)),
                ('concluido_em', models.DateTimeField(blank=True, null=True)),
                ('telefone', models.CharField(blank=True, db_index=True, default='', max_length=32)),
            ],
            options={
                'db_table': 'crm_whatsapp_webhook_fila',
                'ordering': ['prioridade', 'criado_em'],
            },
        ),
        migrations.AddIndex(
            model_name='whatsappwebhookfila',
            index=models.Index(fields=['status', 'prioridade', 'criado_em'], name='crm_wa_wh_status_idx'),
        ),
    ]
