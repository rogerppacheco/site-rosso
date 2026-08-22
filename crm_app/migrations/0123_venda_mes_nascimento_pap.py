# Generated manually for PAP masked birth date month storage

from django.db import migrations, models
import django.core.validators


def forwards_mes_pap(apps, schema_editor):
    Venda = apps.get_model('crm_app', 'Venda')
    for v in Venda.objects.filter(data_nascimento__isnull=False).iterator(chunk_size=500):
        dn = v.data_nascimento
        if dn.year == 1900 and dn.day == 1 and 1 <= dn.month <= 12:
            v.mes_nascimento_pap = dn.month
            v.data_nascimento = None
            v.save(update_fields=['mes_nascimento_pap', 'data_nascimento'])


def backwards_mes_pap(apps, schema_editor):
    from datetime import date
    Venda = apps.get_model('crm_app', 'Venda')
    for v in Venda.objects.filter(mes_nascimento_pap__isnull=False).iterator(chunk_size=500):
        m = v.mes_nascimento_pap
        if m and 1 <= m <= 12:
            v.data_nascimento = date(1900, m, 1)
            v.save(update_fields=['data_nascimento'])


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0122_funil_venda_wpp'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='mes_nascimento_pap',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='Mês (1–12) quando o portal PAP só revela **/MM/**** na data de nascimento.',
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(12),
                ],
                verbose_name='Mês nascimento (PAP)',
            ),
        ),
        migrations.RunPython(forwards_mes_pap, backwards_mes_pap),
    ]
