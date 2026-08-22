# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0133_adiantamento_sabado_esteira'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaosolicitacao',
            name='imagem_anexo',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to='antecipar_instalacao/%Y/%m/',
                verbose_name='Imagem anexo (opcional)',
            ),
        ),
        migrations.AddField(
            model_name='anteciparinstalacaosolicitacao',
            name='resposta_gc_complemento_vendedor',
            field=models.TextField(
                blank=True,
                default='',
                verbose_name='Complemento ao vendedor (texto após a resposta padrão do GC)',
            ),
        ),
        migrations.AlterField(
            model_name='anteciparinstalacaosolicitacao',
            name='tipo_solicitacao',
            field=models.CharField(
                choices=[
                    ('antecipacao', 'Antecipação'),
                    ('reparo', 'Reparo'),
                    ('instalacao_fisica', 'Instalação física / pendência'),
                ],
                default='antecipacao',
                max_length=24,
                verbose_name='Tipo (Antecipação, Reparo ou Instalação física)',
            ),
        ),
    ]
