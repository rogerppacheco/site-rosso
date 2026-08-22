"""Compara data_abertura CRM (DateTime) x ImportacaoOsab (Date)."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db.models import Q
from django.utils import timezone

from crm_app.churn_os_utils import os_variantes
from crm_app.models import ImportacaoOsab, Venda


def main():
    print("=== Tipos de campo ===")
    print(f"CRM Venda.data_abertura: DateTimeField")
    print(f"ImportacaoOsab.data_abertura: DateField (sem hora na espelho)\n")

    osab_by_key = {}
    for o in ImportacaoOsab.objects.exclude(documento__isnull=True).exclude(documento="").iterator(
        chunk_size=5000
    ):
        for k in os_variantes(o.documento):
            osab_by_key.setdefault(k, o)

    stats = Counter()
    amostras = {k: [] for k in ("data_diff", "hora_diff_mesmo_dia", "crm_sem_osab", "osab_sem_data", "crm_sem_data", "iguais")}

    for v in (
        Venda.objects.filter(ativo=True)
        .exclude(Q(ordem_servico__isnull=True) | Q(ordem_servico=""))
        .iterator(chunk_size=500)
    ):
        o = None
        for k in os_variantes(v.ordem_servico):
            o = osab_by_key.get(k)
            if o:
                break
        if not o:
            stats["crm_sem_osab"] += 1
            continue
        if not o.data_abertura:
            stats["osab_sem_data"] += 1
            continue
        if not v.data_abertura:
            stats["crm_sem_data"] += 1
            if len(amostras["crm_sem_data"]) < 5:
                amostras["crm_sem_data"].append((v.id, v.ordem_servico, o.data_abertura))
            continue

        crm_local = timezone.localtime(v.data_abertura)
        crm_date = crm_local.date()
        osab_date = o.data_abertura
        crm_hora = crm_local.time()

        if crm_date != osab_date:
            stats["data_diff"] += 1
            if len(amostras["data_diff"]) < 8:
                amostras["data_diff"].append(
                    (v.id, v.ordem_servico, crm_local.strftime("%Y-%m-%d %H:%M:%S"), str(osab_date))
                )
        elif crm_hora.hour == 0 and crm_hora.minute == 0 and crm_hora.second == 0:
            stats["mesmo_dia_crm_meia_noite"] += 1
        else:
            stats["hora_diff_mesmo_dia"] += 1
            if len(amostras["hora_diff_mesmo_dia"]) < 8:
                amostras["hora_diff_mesmo_dia"].append(
                    (v.id, v.ordem_servico, crm_local.strftime("%Y-%m-%d %H:%M:%S"), str(osab_date))
                )

        if crm_date == osab_date:
            stats["data_igual"] += 1

    total_match = stats["data_diff"] + stats["mesmo_dia_crm_meia_noite"] + stats["hora_diff_mesmo_dia"]
    print("=== Vendas ativas com match OSAB e ambas com data ===")
    print(f"  Total comparável: {total_match}")
    print(f"  Data igual (mesmo dia): {stats['data_igual']}")
    print(f"  Data diferente (dia distinto): {stats['data_diff']}")
    print(f"  Mesmo dia, CRM com hora 00:00:00 (provável import sem hora): {stats['mesmo_dia_crm_meia_noite']}")
    print(f"  Mesmo dia, CRM com hora != meia-noite (espelho OSAB não guarda hora): {stats['hora_diff_mesmo_dia']}")
    print(f"  CRM sem data_abertura (OSAB tem): {stats['crm_sem_data']}")
    print(f"  OSAB sem data_abertura (CRM tem): {stats['osab_sem_data']}")
    print(f"  CRM sem match na espelho: {stats['crm_sem_osab']}")

    for label, rows in amostras.items():
        if not rows:
            continue
        print(f"\n--- Amostra: {label} ---")
        for r in rows:
            print(f"  id={r[0]} os={r[1]} CRM={r[2]} OSAB={r[3]}")


if __name__ == "__main__":
    main()
