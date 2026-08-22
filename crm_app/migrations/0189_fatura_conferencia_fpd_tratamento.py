# Generated manually for FaturaM10 status conferência FPD

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0188_importacaofpd_spd_tpd_faltam_crm'),
    ]

    operations = [
        migrations.AddField(
            model_name='faturam10',
            name='status_origem',
            field=models.CharField(
                choices=[
                    ('FPD', 'Planilha FPD'),
                    ('TRATAMENTO', 'Tratamento (manual)'),
                    ('SISTEMA', 'Sistema'),
                ],
                db_index=True,
                default='SISTEMA',
                help_text='Se o status atual veio do FPD ou foi informado no tratamento',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='faturam10',
            name='conferencia_fpd',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', '—'),
                    ('AGUARDANDO', 'Aguardando confirmação FPD'),
                    ('CONFIRMADO', 'Confirmado na planilha FPD'),
                    ('DIVERGENTE', 'Divergente da planilha FPD'),
                ],
                db_index=True,
                default='',
                help_text='Conferência do status de tratamento com a próxima importação FPD',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='faturam10',
            name='status_informado_tratamento',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Status que o BO informou no tratamento (para conferir no FPD)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='faturam10',
            name='data_status_tratamento',
            field=models.DateTimeField(
                blank=True,
                help_text='Quando o status foi alterado no tratamento',
                null=True,
            ),
        ),
    ]
