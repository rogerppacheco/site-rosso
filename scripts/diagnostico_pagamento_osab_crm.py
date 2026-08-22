"""CRM BOLETO x OSAB CARTÃO DE CRÉDITO — por que não corrigiu?"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from django.db.models import Q

from crm_app.churn_os_utils import os_variantes
from crm_app.models import FormaPagamento, ImportacaoOsab, Venda


def osab_indica_cartao(meio):
    mp = (meio or "").upper()
    return "CART" in mp or "CREDIT" in mp or "CRÉDIT" in mp or "CRÉDIT" in mp


def crm_indica_boleto(nome):
    return "BOLETO" in (nome or "").upper()


def main():
    print("=== FormasPagamento ativas no CRM ===")
    for fp in FormaPagamento.objects.filter(ativo=True).order_by("nome"):
        print(f"  {fp.id}: {fp.nome}")

    print("\nMontando índice OSAB...")
    osab_by_key = {}
    for o in ImportacaoOsab.objects.exclude(documento__isnull=True).exclude(documento="").iterator(
        chunk_size=5000
    ):
        for k in os_variantes(o.documento):
            osab_by_key.setdefault(k, o)

    mismatch = []
    sem_osab = 0
    for v in (
        Venda.objects.filter(ativo=True)
        .exclude(Q(ordem_servico__isnull=True) | Q(ordem_servico=""))
        .select_related("forma_pagamento")
        .iterator(chunk_size=500)
    ):
        os_str = (v.ordem_servico or "").strip()
        o = None
        for k in os_variantes(os_str):
            o = osab_by_key.get(k)
            if o:
                break
        if not o:
            sem_osab += 1
            continue
        if not osab_indica_cartao(o.meio_pagamento):
            continue
        crm_fp = v.forma_pagamento.nome if v.forma_pagamento else ""
        if not crm_indica_boleto(crm_fp):
            continue
        mismatch.append(
            {
                "id": v.id,
                "os": os_str,
                "osab_mp": o.meio_pagamento,
                "crm_fp": crm_fp,
                "bloq": v.bloquear_atualizacao_status_osab,
                "dt_ref": o.dt_ref,
                "situacao": o.situacao,
            }
        )

    print(f"\n=== CRM BOLETO × OSAB CARTÃO: {len(mismatch)} vendas ativas ===")
    print(f"Vendas ativas sem match OSAB (espelho): {sem_osab} (amostra contagem parcial no loop)")
    bloq = sum(1 for x in mismatch if x["bloq"])
    print(f"Com bloquear_atualizacao_status_osab=True: {bloq}")
    print(f"Sem bloqueio (deveriam corrigir na importação): {len(mismatch) - bloq}")

    print("\n--- Amostra (15 primeiras) ---")
    for x in mismatch[:15]:
        print(
            f"  id={x['id']} os={x['os']} osab_mp={x['osab_mp']!r} crm={x['crm_fp']!r} "
            f"bloq={x['bloq']} dt_ref={x['dt_ref']} sit={x['situacao']}"
        )

    # Teste de mapeamento
    print("\n=== Teste mapa pagamento (como na importação) ===")
    import unicodedata

    def normalize_text(text):
        if not text:
            return ""
        text = str(text).upper().strip()
        return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

    mapa = {normalize_text(fp.nome): fp for fp in FormaPagamento.objects.filter(ativo=True)}
    for raw in ["CARTÃO DE CRÉDITO", "CARTAO DE CREDITO", "Cartão de Crédito", "BOLETO"]:
        norm = normalize_text(raw)
        hit = mapa.get(norm)
        if not hit:
            for k, v in mapa.items():
                if norm in k or k in norm:
                    hit = v
                    break
        print(f"  OSAB/entrada {raw!r} -> {hit.nome if hit else 'NAO MAPEADO'}")


if __name__ == "__main__":
    main()
