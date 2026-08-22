from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0158_controle_tt_credito_uso_diario'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlanoValoresComissao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'banda_comissao',
                    models.CharField(
                        choices=[
                            ('500MB', '500 MB'),
                            ('700MB', '700 MB'),
                            ('1GB', '1 GB'),
                            ('PERSONALIZADO', 'Personalizado'),
                        ],
                        default='PERSONALIZADO',
                        max_length=20,
                        verbose_name='Banda nas regras de faixa',
                    ),
                ),
                (
                    'valor_pap',
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True,
                        verbose_name='Comissão PAP (CPF)',
                    ),
                ),
                (
                    'valor_cnpj',
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True,
                        verbose_name='Comissão CNPJ',
                    ),
                ),
                (
                    'propagar_faixas',
                    models.BooleanField(
                        default=True,
                        help_text='Atualiza colunas da banda em Regras por Faixa (COMISSÃO).',
                    ),
                ),
                (
                    'propagar_vendedores',
                    models.BooleanField(
                        default=True,
                        help_text='Cria/atualiza vínculo por plano em cada config de vendedor.',
                    ),
                ),
                (
                    'plano',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='valores_comissao',
                        to='crm_app.plano',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Valores de comissão do plano',
                'verbose_name_plural': 'Valores de comissão dos planos',
                'db_table': 'crm_plano_valores_comissao',
            },
        ),
        migrations.CreateModel(
            name='PlanoValoresComissaoVendedor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('valor_pap', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('valor_cnpj', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                (
                    'config',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='valores_por_plano',
                        to='crm_app.configcomissaovendedor',
                    ),
                ),
                (
                    'plano',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='valores_vendedor',
                        to='crm_app.plano',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Comissão plano × vendedor',
                'verbose_name_plural': 'Comissões plano × vendedor',
                'db_table': 'crm_plano_valores_comissao_vendedor',
            },
        ),
        migrations.AddConstraint(
            model_name='planovalorescomissaovendedor',
            constraint=models.UniqueConstraint(
                fields=('config', 'plano'),
                name='crm_plano_valores_comissao_vendedor_uniq',
            ),
        ),
    ]
