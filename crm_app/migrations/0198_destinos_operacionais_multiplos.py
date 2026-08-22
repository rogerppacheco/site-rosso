# Generated manually for destinos operacionais (grupos + telefones)

from django.db import migrations, models


def migrar_destinos_legado(apps, schema_editor):
    AnteciparInstalacaoConfig = apps.get_model('crm_app', 'AnteciparInstalacaoConfig')
    for config in AnteciparInstalacaoConfig.objects.all():
        changed = False
        telefones = list(config.telefones_destino or [])
        tel_gc = (config.telefone_gc or '').strip()
        if tel_gc and tel_gc not in telefones:
            telefones.append(tel_gc)
            config.telefones_destino = telefones
            changed = True
        if changed:
            config.save(update_fields=['telefones_destino'])
        if config.grupo_id:
            config.grupos_destino.add(config.grupo_id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0197_sync_index_names_qualidade_fpd'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='grupos_destino',
            field=models.ManyToManyField(
                blank=True,
                help_text='Grupos que recebem Antecipação e Sem SLOT (um ou mais).',
                related_name='+',
                to='crm_app.grupodisparo',
                verbose_name='Grupos WhatsApp de destino',
            ),
        ),
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='telefones_destino',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Números WhatsApp individuais que recebem Antecipação e Sem SLOT.',
                verbose_name='Telefones WhatsApp individuais',
            ),
        ),
        migrations.AddField(
            model_name='auditoriasemslotgc',
            name='enviados_grupos',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Chat IDs / nomes dos grupos WhatsApp que receberam o envio.',
            ),
        ),
        migrations.AlterField(
            model_name='anteciparinstalacaoconfig',
            name='grupo',
            field=models.ForeignKey(
                blank=True,
                help_text='Campo legado. Preferir grupos_destino.',
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='+',
                to='crm_app.grupodisparo',
                verbose_name='Grupo WhatsApp (legado)',
            ),
        ),
        migrations.AlterField(
            model_name='auditoriasemslotgc',
            name='enviados_diretoria',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Telefones individuais que receberam o envio (legado: Diretoria).',
            ),
        ),
        migrations.RunPython(migrar_destinos_legado, noop_reverse),
    ]
