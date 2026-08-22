# Generated manually — valor efetivamente pago no sábado (imutável na folha)
from decimal import Decimal, InvalidOperation

from django.db import migrations, models


def _valor_mapa_lancamentos_sabado(apps):
    LancamentoFinanceiro = apps.get_model('crm_app', 'LancamentoFinanceiro')
    mapa = {}
    for lanc in LancamentoFinanceiro.objects.filter(tipo='ADIANTAMENTO_COMISSAO'):
        meta = lanc.metadados if isinstance(lanc.metadados, dict) else {}
        if meta.get('origem') != 'esteira_sabado_agendados':
            continue
        for vid, val in (meta.get('valores_por_venda_id') or {}).items():
            try:
                mapa[int(vid)] = Decimal(str(val))
            except (InvalidOperation, TypeError, ValueError):
                continue
    return mapa


def preencher_valor_pago_sabado(apps, schema_editor):
    Venda = apps.get_model('crm_app', 'Venda')
    mapa_lanc = _valor_mapa_lancamentos_sabado(apps)
    atualizar = []
    for venda in Venda.objects.filter(adiantamento_sabado_marcado=True):
        pago = mapa_lanc.get(venda.id)
        if pago is None and venda.adiantamento_sabado_valor is not None:
            pago = venda.adiantamento_sabado_valor
        if pago is None or pago <= 0:
            continue
        venda.adiantamento_sabado_valor_pago = pago
        venda.adiantamento_sabado_valor = pago
        atualizar.append(venda)
    if atualizar:
        Venda.objects.bulk_update(
            atualizar,
            ['adiantamento_sabado_valor_pago', 'adiantamento_sabado_valor'],
            batch_size=500,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0152_corrigir_data_abertura_osab_local'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='adiantamento_sabado_valor_pago',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Valor efetivamente pago no adiantamento de sábado (base para complemento na folha).',
                max_digits=10,
                null=True,
                verbose_name='Valor pago adiantamento sábado',
            ),
        ),
        migrations.RunPython(preencher_valor_pago_sabado, migrations.RunPython.noop),
    ]
