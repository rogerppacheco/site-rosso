"""Diagnóstico extra: histórico de importações e busca ampla na OSAB."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db.models import Q

from crm_app.models import (
    Venda,
    ImportacaoOsab,
    LogImportacaoOSAB,
    LogImportacaoOSABSnapshotVenda,
    HistoricoAlteracaoVenda,
)
from crm_app.churn_os_utils import os_variantes

IDS = [
    6714, 6709, 5884, 6687, 6707, 6401, 6704, 6711, 6753, 6715, 6728, 6696, 6745,
    6706, 6746, 6716, 6727, 6729, 6718, 6710, 6694, 6685, 6684, 6700, 6708, 6689,
    6722, 6686, 6724, 6692, 6701, 6691, 6725, 6731, 6755, 6683, 6661, 6702, 6738,
    6717, 6699,
]


def main():
    print("=== Ultimos 15 logs OSAB ===")
    for log in LogImportacaoOSAB.objects.order_by("-id")[:15]:
        d = log.detalhes_json or {}
        print(
            f"id={log.id} file={log.nome_arquivo} status={log.status} "
            f"outro_pdv={d.get('crm_sem_osab_outro_pdv', 0)} "
            f"validos={d.get('pedidos_validos_planilha', 0)} "
            f"total={d.get('total_registros', 0)}"
        )

    print("\n=== Busca variantes OS na ImportacaoOsab (41 vendas) ===")
    found_variants = 0
    for v in Venda.objects.filter(id__in=IDS):
        os_crm = (v.ordem_servico or "").strip()
        variants = os_variantes(os_crm)
        hits = []
        for var in variants:
            r = ImportacaoOsab.objects.filter(documento=var).first()
            if r:
                hits.append((var, r.situacao, r.pdv_sap))
        if hits:
            found_variants += 1
            print(f"id={v.id} os={os_crm} FOUND: {hits}")
        else:
            # suffix search
            suffix = os_crm.lstrip("0")[-6:]
            partial = list(
                ImportacaoOsab.objects.filter(documento__endswith=suffix).values_list(
                    "documento", "situacao"
                )[:3]
            )
            print(f"id={v.id} os={os_crm} NOT FOUND (partial *{suffix}: {partial})")

    print(f"\nCom match por variantes: {found_variants}/41")

    print("\n=== Snapshots anteriores (nao AUSENTE) ===")
    for vid in IDS[:5]:
        snaps = (
            LogImportacaoOSABSnapshotVenda.objects.filter(venda_id=vid)
            .exclude(origem="AUSENTE_OSAB")
            .order_by("-log_id")[:2]
        )
        print(f"Venda {vid}:")
        for s in snaps:
            antes = s.valores_antes or {}
            print(
                f"  log={s.log_id} origem={s.origem} os={s.ordem_servico} "
                f"status_antes={antes.get('status_esteira_nome')}"
            )

    print("\n=== Como ficaram INSTALADA (amostra) ===")
    for vid in [6714, 6709, 5884]:
        hist = HistoricoAlteracaoVenda.objects.filter(venda_id=vid).order_by("-id")[:8]
        print(f"\nVenda {vid}:")
        for h in hist:
            se = h.alteracoes.get("status_esteira")
            if se:
                print(f"  {h.data_alteracao}: {se}")


if __name__ == "__main__":
    main()
