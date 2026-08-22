# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0137_auditoria_sem_slot_gc'),
    ]

    operations = [
        migrations.CreateModel(
            name='PendenciaIndevidaRegistro',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('observacao', models.TextField(blank=True)),
                ('tem_evidencia', models.BooleanField(default=False)),
                ('mensagem_enviada', models.TextField(blank=True)),
                ('enviado_gc', models.BooleanField(default=False)),
                ('erros', models.JSONField(blank=True, default=list)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('motivo_pendencia', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pendencias_indevidas', to='crm_app.motivopendencia')),
                ('usuario', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pendencias_indevidas_registradas', to=settings.AUTH_USER_MODEL)),
                ('venda', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pendencias_indevidas', to='crm_app.venda')),
            ],
            options={
                'verbose_name': 'Pendência indevida',
                'verbose_name_plural': 'Pendências indevidas',
                'ordering': ['-criado_em'],
            },
        ),
        migrations.CreateModel(
            name='PendenciaIndevidaAnexo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('arquivo', models.FileField(upload_to='pendencia_indevida/%Y/%m/')),
                ('nome_original', models.CharField(blank=True, max_length=255)),
                ('tipo', models.CharField(choices=[('imagem', 'Imagem'), ('video', 'Vídeo'), ('audio', 'Áudio')], default='imagem', max_length=10)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('registro', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='anexos', to='crm_app.pendenciaindevidaregistro')),
            ],
            options={
                'verbose_name': 'Anexo pendência indevida',
                'verbose_name_plural': 'Anexos pendência indevida',
                'ordering': ['id'],
            },
        ),
    ]
