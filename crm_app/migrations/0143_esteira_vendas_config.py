# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0142_pendencia_cliente_msg_esteira'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EsteiraVendasConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'whatsapp_backoffice',
                    models.CharField(
                        blank=True,
                        default='',
                        help_text='Número usado no botão/mensagem de dúvidas ao marcar pendência tipo CLIENTE.',
                        max_length=20,
                        verbose_name='WhatsApp BackOffice (pendência cliente)',
                    ),
                ),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                (
                    'atualizado_por',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='+',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Config. Esteira de Vendas',
                'verbose_name_plural': 'Config. Esteira de Vendas',
            },
        ),
    ]
