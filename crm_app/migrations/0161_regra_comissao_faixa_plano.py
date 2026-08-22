from django.db import migrations, models
import django.db.models.deletion


def popular_matriz_faixa_plano(apps, schema_editor):
    Plano = apps.get_model('crm_app', 'Plano')
    RegraComissaoFaixa = apps.get_model('crm_app', 'RegraComissaoFaixa')
    RegraComissaoFaixaPlano = apps.get_model('crm_app', 'RegraComissaoFaixaPlano')

    def banda_nome(nome: str) -> str | None:
        n = (nome or '').upper().replace(' ', '')
        if '500' in n:
            return '500MB'
        if '700' in n:
            return '700MB'
        if '1GB' in n or '1G' in n:
            return '1GB'
        return None

    def legado(faixa, banda: str):
        if banda == '500MB':
            return faixa.valor_500mb_pap, faixa.valor_500mb_cnpj
        if banda == '700MB':
            return faixa.valor_700mb_pap, faixa.valor_700mb_cnpj
        if banda == '1GB':
            return faixa.valor_1gb_pap, faixa.valor_1gb_cnpj
        return None, None

    for plano in Plano.objects.filter(ativo=True):
        banda = banda_nome(plano.nome)
        for faixa in RegraComissaoFaixa.objects.all():
            pap, cnpj = legado(faixa, banda) if banda else (None, None)
            RegraComissaoFaixaPlano.objects.get_or_create(
                faixa_id=faixa.id,
                plano_id=plano.id,
                defaults={'valor_pap': pap, 'valor_cnpj': cnpj},
            )


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0160_plano_valores_propagar_faixas_default_false'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegraComissaoFaixaPlano',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('valor_pap', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('valor_cnpj', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                (
                    'faixa',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='valores_por_plano',
                        to='crm_app.regracomissaofaixa',
                    ),
                ),
                (
                    'plano',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='valores_faixa_comissao',
                        to='crm_app.plano',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Comissão faixa × plano',
                'verbose_name_plural': 'Comissões faixa × plano',
                'db_table': 'crm_regra_comissao_faixa_plano',
            },
        ),
        migrations.AddConstraint(
            model_name='regracomissaofaixaplano',
            constraint=models.UniqueConstraint(
                fields=('faixa', 'plano'),
                name='crm_regra_comissao_faixa_plano_uniq',
            ),
        ),
        migrations.RunPython(popular_matriz_faixa_plano, migrations.RunPython.noop),
    ]
