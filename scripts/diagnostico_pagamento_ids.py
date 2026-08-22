"""Diagnóstico detalhado pagamento OSAB x CRM para vendas específicas."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from crm_app.churn_os_utils import os_variantes
from crm_app.models import HistoricoAlteracaoVenda, ImportacaoOsab, LogImportacaoOSAB, Venda

IDS_41 = [
    6714, 6709, 5884, 6687, 6707, 6401, 6704, 6711, 6753, 6715, 6728, 6696, 6745,
    6706, 6746, 6716, 6727, 6729, 6718, 6710, 6694, 6685, 6684, 6700, 6708, 6689,
    6722, 6686, 6724, 6692, 6701, 6691, 6725, 6731, 6755, 6683, 6661, 6702, 6738,
    6717, 6699,
]


def find_osab(v):
    os_str = (v.ordem_servico or "").strip()
    for k in os_variantes(os_str):
        o = ImportacaoOsab.objects.filter(documento=k).first()
        if o:
            return o
    return None


def main():
    ids = IDS_41 + [3288, 6497, 6506]
    print("=== Pagamento CRM x OSAB ===\n")
    mm = 0
    sem_osab = 0
    for vid in ids:
        v = Venda.objects.filter(id=vid).select_related("forma_pagamento").first()
        if not v:
            print(f"id={vid}: nao encontrada")
            continue
        o = find_osab(v)
        crm = v.forma_pagamento.nome if v.forma_pagamento else "-"
        if not o:
            sem_osab += 1
            print(f"id={vid} os={v.ordem_servico} CRM={crm} OSAB=NAO NA BASE")
            continue
        osab_mp = o.meio_pagamento or "-"
        diff = crm.upper() != (osab_mp or "").upper() and not (
            ("BOLETO" in crm.upper() and "BOLETO" in osab_mp.upper())
            or ("CART" in crm.upper() and "CART" in osab_mp.upper())
            or ("DEBIT" in crm.upper() or "DÉBIT" in crm.upper())
            and ("DEBIT" in osab_mp.upper() or "DÉBIT" in osab_mp.upper())
        )
        flag = " *** DIVERGENTE ***" if diff else ""
        if diff:
            mm += 1
        print(
            f"id={vid} os={v.ordem_servico} CRM={crm} OSAB={osab_mp} "
            f"bloq={v.bloquear_atualizacao_status_osab} dt_ref={o.dt_ref}{flag}"
        )
        # hist pagamento
        for h in HistoricoAlteracaoVenda.objects.filter(venda_id=vid).order_by("-id")[:5]:
            alt = h.alteracoes
            if "forma_pagamento" in alt or "osab_bloqueado" in alt:
                print(f"    hist {h.data_alteracao}: {alt}")

    print(f"\nDivergentes: {mm} | Sem OSAB: {sem_osab} | Total consultado: {len(ids)}")

    # Verificar se pedidos aparecem nos logs de importação recentes
    print("\n=== Presença nos logs OSAB recentes (111, 110, 109) ===")
    for lid in [111, 110, 109]:
        log = LogImportacaoOSAB.objects.filter(id=lid).first()
        if not log or not log.detalhes_json:
            continue
        logs = log.detalhes_json.get("logs_detalhados") or []
        pedidos = {str(x.get("pedido")) for x in logs}
        found = []
        for v in Venda.objects.filter(id__in=IDS_41[:5]):
            os_sem = (v.ordem_servico or "").lstrip("0")
            if v.ordem_servico in pedidos or os_sem in pedidos:
                found.append(v.id)
        print(f"Log {lid} ({log.nome_arquivo}): {len(logs)} linhas, amostra 41 encontradas: {found}")


if __name__ == "__main__":
    main()
