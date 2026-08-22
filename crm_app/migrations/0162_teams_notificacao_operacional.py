from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0161_regra_comissao_faixa_plano'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='teams_notificacao_ativo',
            field=models.BooleanField(
                default=False,
                help_text='Envia cópia das mensagens operacionais (Sem SLOT, Antecipar, etc.) ao canal Teams via n8n.',
                verbose_name='Notificação Teams ativa',
            ),
        ),
        migrations.AddField(
            model_name='auditoriasemslotgc',
            name='enviado_teams',
            field=models.BooleanField(default=False, verbose_name='Enviado ao Teams'),
        ),
        migrations.AddField(
            model_name='anteciparinstalacaosolicitacao',
            name='enviado_teams',
            field=models.BooleanField(default=False, verbose_name='Enviado ao Teams'),
        ),
    ]
