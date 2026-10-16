from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0035_credencialrobopap_brpronto'),
    ]

    operations = [
        migrations.AlterField(
            model_name='credencialrobopap',
            name='funcao',
            field=models.CharField(
                choices=[
                    ('CONSULTA_ESTEIRA', 'Consulta PAP (Esteira)'),
                    ('WHATSAPP_BOT', 'Bot do WhatsApp (Crédito, OS, etc)'),
                    ('HISTORICO_VENDAS', 'Auditoria/Histórico (Excel PAP)'),
                    ('BRPRONTO_GED', 'Br Pronto / GED360 (Biometria)'),
                    ('IMPORT_OSAB_BI', 'Importação OSAB (BI Dinâmica)'),
                    ('OUTROS', 'Outros'),
                ],
                max_length=50,
                verbose_name='Função',
            ),
        ),
    ]
