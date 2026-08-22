"""Auditoria rápida: INSTALADA OUTRO PDV (produção)."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db import connection
from django.db.models import Q

from crm_app.churn_os_utils import os_variantes
from crm_app.models import ImportacaoOsab, LogImportacaoOSABSnapshotVenda, StatusCRM, Venda


def main():
    st_outro = StatusCRM.objects.filter(tipo="Esteira", nome__iexact="INSTALADA OUTRO PDV").first()
    if not st_outro:
        print("Status não encontrado.")
        return

    print("Montando set OSAB...")
    osab_set = set()
    for doc in ImportacaoOsab.objects.values_list("documento", flat=True).iterator(chunk_size=8000):
        if doc:
            osab_set.update(os_variantes(doc))

    vendas = list(
        Venda.objects.filter(ativo=True, status_esteira=st_outro)
        .values("id", "ordem_servico", "data_instalacao", "data_abertura")
    )
    total = len(vendas)
    sem_os = Venda.objects.filter(ativo=True, status_esteira=st_outro).filter(
        Q(ordem_servico__isnull=True) | Q(ordem_servico="")
    ).count()

    snap_ids = set(
        LogImportacaoOSABSnapshotVenda.objects.filter(
            origem=LogImportacaoOSABSnapshotVenda.ORIGEM_AUSENTE_OSAB,
            venda_id__in=[v["id"] for v in vendas],
        ).values_list("venda_id", flat=True)
    )
    snap_por_log = Counter(
        LogImportacaoOSABSnapshotVenda.objects.filter(
            origem=LogImportacaoOSABSnapshotVenda.ORIGEM_AUSENTE_OSAB,
            venda_id__in=[v["id"] for v in vendas],
        ).values_list("log_id", flat=True)
    )

    # Histórico com mensagem de pós-processamento (bulk SQL)
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT venda_id
            FROM crm_historico_alteracao_venda
            WHERE venda_id = ANY(%s)
              AND (
                alteracoes::text ILIKE '%%não consta na base OSAB%%'
                OR alteracoes::text ILIKE '%%nao consta na base osab%%'
              )
            """,
            [[v["id"] for v in vendas]],
        )
        hist_ausente_ids = {row[0] for row in cur.fetchall()}

    cat = Counter()
    ids_restaurar = []
    ids_consta_osab = []
    ids_so_data_inst = []
    ids_snap_ou_hist = []
    ids_restantes = []

    for v in vendas:
        os_str = (v["ordem_servico"] or "").strip()
        in_osab = bool(os_variantes(os_str) & osab_set) if os_str else False
        tem_inst = v["data_instalacao"] is not None
        snap = v["id"] in snap_ids
        hist = v["id"] in hist_ausente_ids

        if in_osab:
            cat["consta_osab"] += 1
            ids_restaurar.append(v["id"])
            ids_consta_osab.append(v["id"])
        elif tem_inst:
            cat["data_instalacao"] += 1
            ids_restaurar.append(v["id"])
            ids_so_data_inst.append(v["id"])
        elif snap or hist:
            cat["pos_process_ausente"] += 1
            ids_restaurar.append(v["id"])
            ids_snap_ou_hist.append(v["id"])
        else:
            cat["indeterminado"] += 1
            ids_restantes.append(v["id"])

    print(f"=== INSTALADA OUTRO PDV ativas: {total} (+ {sem_os} sem O.S.) ===")
    print(f"ImportacaoOsab espelho: {ImportacaoOsab.objects.count()} docs / {len(osab_set)} variantes\n")
    print("--- Classificação ---")
    print(f"  Consta na base OSAB (erro claro):           {cat['consta_osab']}")
    print(f"  Com data_instalacao (deveria ser INSTALADA): {cat['data_instalacao']}")
    print(f"  Pós-process. ausentes (snap/hist):          {cat['pos_process_ausente']}")
    print(f"  Indeterminados (sem inst, ausente OSAB):    {cat['indeterminado']}")
    print(f"\n>>> Restaurar para INSTALADA (erro provável): {len(ids_restaurar)}")
    print(f">>> Manter OUTRO PDV (revisar manual):        {len(ids_restantes)}")

    print(f"\nSnapshots AUSENTE_OSAB neste grupo: {len(snap_ids)}")
    print(f"Top logs: {snap_por_log.most_common(8)}")

    if ids_consta_osab:
        print("\nAmostra consta OSAB:", ids_consta_osab[:6])
    if ids_restantes:
        print("\nAmostra indeterminados:")
        for vid in ids_restantes[:8]:
            v = next(x for x in vendas if x["id"] == vid)
            print(f"  id={vid} os={v['ordem_servico']} abertura={v['data_abertura']}")

    out = os.path.join(os.path.dirname(__file__), "outro_pdv_restaurar_ids.txt")
    with open(out, "w", encoding="utf-8") as f:
        for i in sorted(set(ids_restaurar)):
            f.write(f"{i}\n")
    out2 = os.path.join(os.path.dirname(__file__), "outro_pdv_revisar_ids.txt")
    with open(out2, "w", encoding="utf-8") as f:
        for i in sorted(ids_restantes):
            f.write(f"{i}\n")
    print(f"\nArquivos: {out} ({len(set(ids_restaurar))}), {out2} ({len(ids_restantes)})")


if __name__ == "__main__":
    main()
