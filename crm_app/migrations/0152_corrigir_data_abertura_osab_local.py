# Corrige data_abertura espelho OSAB: DateField virou UTC 00:00 → meia-noite local na data correta

from datetime import datetime, time, timedelta

from django.db import migrations
from django.utils import timezone


def corrigir_data_abertura_osab_local(apps, schema_editor):
    ImportacaoOsab = apps.get_model("crm_app", "ImportacaoOsab")
    tz = timezone.get_current_timezone()
    batch = []
    for obj in ImportacaoOsab.objects.exclude(data_abertura__isnull=True).iterator(chunk_size=2000):
        dt = obj.data_abertura
        if not dt:
            continue
        # Data calendário original (campo era DateField)
        if timezone.is_aware(dt):
            d = timezone.localtime(dt).date()
            # Heurística: migração UTC 00:00 aparece como 21:00 dia anterior em BR
            loc = timezone.localtime(dt)
            if loc.hour == 21 and loc.minute == 0 and loc.second == 0:
                d = (loc + timedelta(days=1)).date()
        else:
            d = dt.date()
        obj.data_abertura = timezone.make_aware(datetime.combine(d, time.min), tz)
        batch.append(obj)
        if len(batch) >= 2000:
            ImportacaoOsab.objects.bulk_update(batch, ["data_abertura"], batch_size=2000)
            batch = []
    if batch:
        ImportacaoOsab.objects.bulk_update(batch, ["data_abertura"], batch_size=2000)


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0151_importacaoosab_data_abertura_datetime"),
    ]

    operations = [
        migrations.RunPython(corrigir_data_abertura_osab_local, migrations.RunPython.noop),
    ]
