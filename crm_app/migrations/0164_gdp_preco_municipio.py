# Generated manually for GDP preços por município

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0163_delete_whatsappwebhookfila_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='plano',
            name='gdp_indice_oferta',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Quando há mais de uma oferta com a mesma velocidade (ex.: dois planos 1GB), use 0 ou 1.',
                verbose_name='Índice oferta GDP',
            ),
        ),
        migrations.AddField(
            model_name='plano',
            name='gdp_velocidade_mbps',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Velocidade usada na tabela GDP (ex.: 500, 600, 800, 1000). Se vazio, infere pelo nome.',
                null=True,
                verbose_name='Velocidade GDP (Mbps)',
            ),
        ),
        migrations.CreateModel(
            name='LogImportacaoGdpPreco',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome_arquivo', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[('PROCESSANDO', 'Processando'), ('SUCESSO', 'Sucesso'), ('ERRO', 'Erro'), ('PARCIAL', 'Parcial')], max_length=20)),
                ('vigente', models.BooleanField(default=False, help_text='Importação ativa usada para consulta de preços.')),
                ('tamanho_arquivo', models.IntegerField(blank=True, default=0, null=True)),
                ('iniciado_em', models.DateTimeField(auto_now_add=True)),
                ('finalizado_em', models.DateTimeField(blank=True, null=True)),
                ('duracao_segundos', models.IntegerField(blank=True, null=True)),
                ('total_municipios', models.IntegerField(default=0)),
                ('total_precos', models.IntegerField(default=0)),
                ('mensagem', models.TextField(blank=True, null=True)),
                ('mensagem_erro', models.TextField(blank=True, null=True)),
                ('detalhes_json', models.JSONField(blank=True, default=dict, null=True)),
                ('usuario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Log Importação GDP Preços',
                'verbose_name_plural': 'Logs Importação GDP Preços',
                'db_table': 'crm_log_importacao_gdp_preco',
                'ordering': ['-iniciado_em'],
            },
        ),
        migrations.CreateModel(
            name='GdpPrecoMunicipio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uf', models.CharField(db_index=True, max_length=2)),
                ('municipio', models.CharField(db_index=True, max_length=120)),
                ('municipio_normalizado', models.CharField(db_index=True, max_length=120)),
                ('cod_ibge', models.CharField(blank=True, db_index=True, max_length=10, null=True)),
                ('meio_pagamento', models.CharField(choices=[('CARTAO', 'Cartão de crédito'), ('DACC', 'Débito automático'), ('BOLETO', 'Boleto')], db_index=True, max_length=10)),
                ('velocidade_mbps', models.PositiveIntegerField(db_index=True)),
                ('indice_oferta', models.PositiveSmallIntegerField(default=0)),
                ('valor', models.DecimalField(decimal_places=2, max_digits=10)),
                ('log_importacao', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='precos', to='crm_app.logimportacaogdppreco')),
            ],
            options={
                'verbose_name': 'Preço GDP por município',
                'verbose_name_plural': 'Preços GDP por município',
                'db_table': 'crm_gdp_preco_municipio',
            },
        ),
        migrations.AddIndex(
            model_name='gdpprecomunicipio',
            index=models.Index(fields=['municipio_normalizado', 'uf', 'meio_pagamento'], name='crm_gdp_pre_municip_8f0a2a_idx'),
        ),
        migrations.AddIndex(
            model_name='gdpprecomunicipio',
            index=models.Index(fields=['cod_ibge', 'meio_pagamento'], name='crm_gdp_pre_cod_ib_5d4b1c_idx'),
        ),
        migrations.AddConstraint(
            model_name='gdpprecomunicipio',
            constraint=models.UniqueConstraint(
                fields=('log_importacao', 'uf', 'municipio_normalizado', 'meio_pagamento', 'velocidade_mbps', 'indice_oferta'),
                name='uniq_gdp_preco_municipio_oferta',
            ),
        ),
        migrations.RunPython(
            code=lambda apps, schema_editor: _popular_mapeamento_planos_nio(apps),
            reverse_code=migrations.RunPython.noop,
        ),
    ]


def _popular_mapeamento_planos_nio(apps) -> None:
    Plano = apps.get_model('crm_app', 'Plano')
    for plano in Plano.objects.filter(operadora__nome__iexact='NIO'):
        nome = (plano.nome or '').upper()
        updates = {}
        if '500' in nome:
            updates = {'gdp_velocidade_mbps': 500, 'gdp_indice_oferta': 0}
        elif '700' in nome or 'SUPER' in nome:
            updates = {'gdp_velocidade_mbps': 800, 'gdp_indice_oferta': 0}
        elif 'ULTRA' in nome or '1GB' in nome:
            updates = {'gdp_velocidade_mbps': 1000, 'gdp_indice_oferta': 1}
        if updates:
            Plano.objects.filter(pk=plano.pk).update(**updates)
