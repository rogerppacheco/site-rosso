# Generated manually for Record Informa filters

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0166_rename_crm_gdp_pre_municip_8f0a2a_idx_crm_gdp_pre_municip_c9a980_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='comunicado',
            name='canal_alvo',
            field=models.CharField(
                choices=[
                    ('TODOS', 'Todos'),
                    ('PAP', 'PAP'),
                    ('DIGITAL', 'Digital'),
                    ('RECEPTIVO', 'Receptivo'),
                    ('PARCEIRO', 'Parceiro'),
                ],
                default='TODOS',
                max_length=20,
                verbose_name='Canal Alvo',
            ),
        ),
        migrations.AddField(
            model_name='comunicado',
            name='cluster_alvo',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Filtro por cluster (vazio ou TODOS = todos). Ex: CLUSTER_1, CLUSTER_2, CLUSTER_3',
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name='comunicado',
            name='representatividade_minima',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='0 = todos. Filtra vendedores com participação mínima no volume do mês (O.S. cadastradas).',
                verbose_name='Representatividade mínima (%)',
            ),
        ),
        migrations.AddField(
            model_name='comunicado',
            name='status_destinatarios',
            field=models.CharField(
                choices=[
                    ('somente_ativos', 'Somente ativos'),
                    ('somente_inativos', 'Somente inativos'),
                    ('todos', 'Todos'),
                ],
                default='somente_ativos',
                help_text='Define se o envio individual considera usuários ativos, inativos ou todos.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='comunicado',
            name='vendedor',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='comunicados_direcionados',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Vendedor específico',
            ),
        ),
    ]
