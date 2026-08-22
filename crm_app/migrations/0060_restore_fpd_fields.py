# Generated manually to restore FPD fields removed in previous migrations
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0059_faturam10_erro_busca_faturam10_origem_busca_and_more'),
    ]

    operations = [
        # FaturaM10 FPD fields
        migrations.AddField(
            model_name='faturam10',
            name='data_importacao_fpd',
            field=models.DateTimeField(blank=True, null=True, help_text='Data da última importação FPD'),
        ),
        migrations.AddField(
            model_name='faturam10',
            name='ds_status_fatura_fpd',
            field=models.CharField(max_length=50, blank=True, null=True, help_text='DS_STATUS_FATURA do arquivo FPD'),
        ),
        migrations.AddField(
            model_name='faturam10',
            name='dt_pagamento_fpd',
            field=models.DateField(blank=True, null=True, help_text='DT_PAGAMENTO do arquivo FPD'),
        ),
        migrations.AddField(
            model_name='faturam10',
            name='id_contrato_fpd',
            field=models.CharField(max_length=100, blank=True, null=True, help_text='ID_CONTRATO do arquivo FPD'),
        ),
        # LogImportacaoFPD fields used in views
        migrations.AddField(
            model_name='logimportacaofpd',
            name='tamanho_arquivo',
            field=models.IntegerField(default=0, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='iniciado_em',
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='finalizado_em',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='duracao_segundos',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='total_processadas',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='total_contratos_nao_encontrados',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='total_valor_importado',
            field=models.DecimalField(max_digits=15, decimal_places=2, default=0),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='mensagem_erro',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='detalhes_json',
            field=models.JSONField(default=dict, blank=True, null=True),
        ),
        migrations.AddField(
            model_name='logimportacaofpd',
            name='exemplos_nao_encontrados',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='logimportacaofpd',
            name='status',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('PROCESSANDO', 'Processando'),
                    ('SUCESSO', 'Sucesso'),
                    ('ERRO', 'Erro'),
                    ('PARCIAL', 'Parcial'),
                ],
            ),
        ),
    ]
