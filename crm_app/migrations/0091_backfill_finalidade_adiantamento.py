# Backfill: faixas com nome "Adiantamento" passam a ter finalidade='ADIANTAMENTO'

from django.db import migrations


def set_adiantamento_finalidade(apps, schema_editor):
    RegraComissaoFaixa = apps.get_model('crm_app', 'RegraComissaoFaixa')
    RegraComissaoFaixa.objects.filter(faixa_nome__iexact='Adiantamento').update(finalidade='ADIANTAMENTO')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0090_regra_faixa_finalidade'),
    ]

    operations = [
        migrations.RunPython(set_adiantamento_finalidade, noop),
    ]
