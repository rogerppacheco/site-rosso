from django.db import migrations, models


NOME_CONCLUIDO = 'Concluído com sucesso'


def seed_status_concluido(apps, schema_editor):
    StatusAgendamento = apps.get_model('crm_app', 'StatusAgendamento')
    StatusAgendamento.objects.get_or_create(
        nome=NOME_CONCLUIDO,
        defaults={'ordem': 50, 'cor': '#198754', 'ativo': True},
    )


def unseed_status_concluido(apps, schema_editor):
    StatusAgendamento = apps.get_model('crm_app', 'StatusAgendamento')
    StatusAgendamento.objects.filter(nome=NOME_CONCLUIDO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0176_venda_pap_status_consulta_e_modo_consulta_aba'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='pap_status_consulta_erro',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Último erro da consulta STATUS PAP na Esteira (vazio = sucesso).',
                max_length=255,
                verbose_name='Consulta PAP (erro)',
            ),
        ),
        migrations.RunPython(seed_status_concluido, unseed_status_concluido),
    ]
