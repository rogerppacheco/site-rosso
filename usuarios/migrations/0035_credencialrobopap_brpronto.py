from django.db import migrations, models


def copiar_logins_brpronto(apps, schema_editor):
    Usuario = apps.get_model('usuarios', 'Usuario')
    Credencial = apps.get_model('usuarios', 'CredencialRoboPAP')
    existentes = set(Credencial.objects.filter(funcao='BRPRONTO_GED').values_list('matricula', flat=True))
    usuarios = (
        Usuario.objects.filter(is_active=True, brpronto_disponivel_para_automacao=True)
        .exclude(brpronto_login__isnull=True).exclude(brpronto_login='')
        .exclude(brpronto_senha__isnull=True).exclude(brpronto_senha='')
    )
    for usuario in usuarios:
        login = usuario.brpronto_login.strip()
        if login in existentes:
            continue
        Credencial.objects.create(
            funcao='BRPRONTO_GED',
            matricula=login,
            senha=usuario.brpronto_senha,
            dominio=(usuario.brpronto_dominio or 'BrPronto').strip(),
            ativo=True,
        )
        existentes.add(login)


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0034_usuario_operadoras_permitidas'),
    ]

    operations = [
        migrations.AddField(
            model_name='credencialrobopap',
            name='dominio',
            field=models.CharField(blank=True, default='', help_text='Domínio no login do Br Pronto (ex.: BrPronto). Só para a função Br Pronto.', max_length=100, verbose_name='Domínio'),
        ),
        migrations.AlterField(
            model_name='credencialrobopap',
            name='funcao',
            field=models.CharField(choices=[('CONSULTA_ESTEIRA', 'Consulta PAP (Esteira)'), ('WHATSAPP_BOT', 'Bot do WhatsApp (Crédito, OS, etc)'), ('HISTORICO_VENDAS', 'Auditoria/Histórico (Excel PAP)'), ('BRPRONTO_GED', 'Br Pronto / GED360 (Biometria)'), ('OUTROS', 'Outros')], max_length=50, verbose_name='Função'),
        ),
        migrations.RunPython(copiar_logins_brpronto, migrations.RunPython.noop),
    ]
