# Generated manually — reversão de importação OSAB

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0148_cliente_venda_classificacao_mei'),
    ]

    operations = [
        migrations.AddField(
            model_name='logimportacaoosab',
            name='revertido_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='logimportacaoosab',
            name='revertido_por',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='importacoes_osab_revertidas',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='logimportacaoosab',
            name='status',
            field=models.CharField(
                choices=[
                    ('PROCESSANDO', 'Processando'),
                    ('SUCESSO', 'Sucesso'),
                    ('ERRO', 'Erro'),
                    ('PARCIAL', 'Parcial'),
                    ('REVERTIDO', 'Revertido'),
                ],
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='LogImportacaoOSABSnapshotVenda',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ordem_servico', models.CharField(blank=True, default='', max_length=50)),
                ('origem', models.CharField(
                    choices=[
                        ('PLANILHA', 'Planilha OSAB'),
                        ('AUSENTE_OSAB', 'CRM ausente na base OSAB'),
                    ],
                    max_length=20,
                )),
                ('valores_antes', models.JSONField(default=dict)),
                ('log', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='snapshots_vendas',
                    to='crm_app.logimportacaoosab',
                )),
                ('venda', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='snapshots_importacao_osab',
                    to='crm_app.venda',
                )),
            ],
            options={
                'verbose_name': 'Snapshot reversão OSAB',
                'verbose_name_plural': 'Snapshots reversão OSAB',
            },
        ),
        migrations.AddConstraint(
            model_name='logimportacaoosabsnapshotvenda',
            constraint=models.UniqueConstraint(
                fields=('log', 'venda'),
                name='uniq_osab_snapshot_log_venda',
            ),
        ),
    ]
