"""Reverte sincronização data_abertura OSAB→CRM feita com espelho só-data (UTC)."""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db import transaction
from django.utils import timezone

from crm_app.models import HistoricoAlteracaoVenda, Venda


def parse_local_dt(s):
    s = (s or "").strip()
    if s == "-":
        return None
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return timezone.make_aware(naive, timezone.get_current_timezone())


def main():
    pattern = "sincronização DATA_ABERTURA OSAB"
    hist = HistoricoAlteracaoVenda.objects.filter(
        alteracoes__data_abertura__icontains=pattern
    ).order_by("id")
    print(f"Históricos a reverter: {hist.count()}")

    vendas_map = {}
    for h in hist.iterator():
        msg = h.alteracoes.get("data_abertura") or ""
        m = re.search(r"De '([^']*)' para ", msg)
        if not m:
            continue
        antes = parse_local_dt(m.group(1))
        vendas_map[h.venda_id] = (antes, h)

    vendas = list(Venda.objects.filter(id__in=vendas_map.keys()))
    restaurar = []
    for v in vendas:
        antes, _h = vendas_map[v.id]
        if v.data_abertura != antes:
            v.data_abertura = antes
            restaurar.append(v)

    print(f"Restaurando {len(restaurar)} vendas...")
    with transaction.atomic():
        Venda.objects.bulk_update(restaurar, ["data_abertura"], batch_size=500)
        HistoricoAlteracaoVenda.objects.bulk_create(
            [
                HistoricoAlteracaoVenda(
                    venda_id=v.id,
                    usuario=None,
                    alteracoes={
                        "data_abertura": "Revertido sync data_abertura OSAB (espelho ainda sem hora correta)",
                    },
                )
                for v in restaurar
            ],
            batch_size=500,
        )
    print("OK")


if __name__ == "__main__":
    main()
