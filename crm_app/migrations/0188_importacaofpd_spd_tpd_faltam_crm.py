# Generated manually for FPD/SPD/TPD import fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0187_whatsapp_integracao_whatsatende'),
    ]

    operations = [
        migrations.AddField(
            model_name='importacaofpd',
            name='indicador',
            field=models.CharField(
                choices=[('FPD', '1ª fatura (FPD)'), ('SPD', '2ª fatura (SPD)'), ('TPD', '3ª fatura (TPD)')],
                db_index=True,
                default='FPD',
                help_text='FPD=1ª, SPD=2ª, TPD=3ª fatura',
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='numero_fatura_m10',
            field=models.PositiveSmallIntegerField(
                db_index=True,
                default=1,
                help_text='Número da fatura no M-10 (1/2/3)',
            ),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='ds_sit_fatura',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='ABERTA / FECHADA (planilha)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='faixa',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Faixa de atraso da planilha',
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='municipio',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='uf',
            field=models.CharField(blank=True, default='', max_length=2),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='cd_vendedor_original',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='nm_pdv',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='nm_gc',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='importacaofpd',
            name='match_status',
            field=models.CharField(
                choices=[
                    ('MATCHED', 'Vinculado ao CRM'),
                    ('FALTA_CRM', 'Falta no CRM'),
                    ('ORFAO', 'Órfão (sem CPF/venda)'),
                ],
                db_index=True,
                default='MATCHED',
                help_text='Resultado do vínculo com ContratoM10/Venda',
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='importacaofpd',
            index=models.Index(fields=['indicador', 'ds_sit_fatura'], name='crm_app_imp_indicad_sit_idx'),
        ),
        migrations.AddIndex(
            model_name='importacaofpd',
            index=models.Index(fields=['match_status', 'indicador'], name='crm_app_imp_match_ind_idx'),
        ),
        migrations.AddIndex(
            model_name='importacaofpd',
            index=models.Index(fields=['nr_ordem', 'indicador'], name='crm_app_imp_ordem_ind_idx'),
        ),
    ]
