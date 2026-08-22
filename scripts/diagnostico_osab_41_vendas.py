"""Diagnóstico: 41 vendas marcadas INSTALADA OUTRO PDV na importação OSAB #111."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from crm_app.models import (
    Venda,
    ImportacaoOsab,
    LogImportacaoOSABSnapshotVenda,
    HistoricoAlteracaoVenda,
    LogImportacaoOSAB,
)

IDS = [
    6714, 6709, 5884, 6687, 6707, 6401, 6704, 6711, 6753, 6715, 6728, 6696, 6745,
    6706, 6746, 6716, 6727, 6729, 6718, 6710, 6694, 6685, 6684, 6700, 6708, 6689,
    6722, 6686, 6724, 6692, 6701, 6691, 6725, 6731, 6755, 6683, 6661, 6702, 6738,
    6717, 6699,
]


def normalize_pedido(pedido):
    if pedido is None:
        return None
    pedido_str = str(pedido).strip()
    if pedido_str.endswith(".0"):
        pedido_str = pedido_str[:-2]
    return pedido_str


def main():
    vendas = list(
        Venda.objects.filter(id__in=IDS).select_related("status_esteira", "vendedor")
    )
    print(f"Vendas encontradas: {len(vendas)}")

    osab_docs = set()
    for doc in ImportacaoOsab.objects.values_list("documento", flat=True).iterator(
        chunk_size=8000
    ):
        if not doc:
            continue
        s = str(doc).strip()
        if s:
            osab_docs.add(s)
        n = normalize_pedido(doc)
        if n:
            osab_docs.add(n)

    print(f"Total ImportacaoOsab: {ImportacaoOsab.objects.count()} (set normalizado: {len(osab_docs)})")

    sem_osab = 0
    for v in sorted(vendas, key=lambda x: x.id):
        os_str = (v.ordem_servico or "").strip()
        norm = normalize_pedido(os_str)
        in_table = os_str in osab_docs or (norm and norm in osab_docs)
        in_direct = ImportacaoOsab.objects.filter(documento=os_str).exists() if os_str else False
        status = v.status_esteira.nome if v.status_esteira else "(vazio)"
        if not in_table:
            sem_osab += 1
        print(
            f"id={v.id} os={os_str} status={status} "
            f"in_osab_set={in_table} in_osab_direct={in_direct} "
            f"abertura={v.data_abertura} inst={v.data_instalacao}"
        )

    print(f"\nSem match em ImportacaoOsab: {sem_osab}/{len(vendas)}")

    snaps = LogImportacaoOSABSnapshotVenda.objects.filter(venda_id__in=IDS, log_id=111)
    print(f"\nSnapshots log 111: {snaps.count()}")
    print(f"  ORIGEM AUSENTE_OSAB: {snaps.filter(origem='AUSENTE_OSAB').count()}")
    print(f"  ORIGEM planilha: {snaps.exclude(origem='AUSENTE_OSAB').count()}")

    log = LogImportacaoOSAB.objects.filter(id=111).first()
    if log:
        d = log.detalhes_json or {}
        print(f"\nLog 111: arquivo={log.nome_arquivo} status={log.status}")
        print(f"  finalizado={log.finalizado_em}")
        print(f"  crm_sem_osab_outro_pdv={d.get('crm_sem_osab_outro_pdv')}")
        print(f"  crm_sem_osab_nao_consta={d.get('crm_sem_osab_nao_consta')}")
        print(f"  pedidos_validos={d.get('pedidos_validos_planilha')}")
        print(f"  total_registros={d.get('total_registros')}")

    # Histórico recente de status para amostra
    print("\n--- Histórico (amostra id=6714) ---")
    for h in HistoricoAlteracaoVenda.objects.filter(venda_id=6714).order_by("-id")[:5]:
        alt = h.alteracoes.get("status_esteira", h.alteracoes)
        print(f"  {h.data_alteracao}: {alt}")


if __name__ == "__main__":
    main()
