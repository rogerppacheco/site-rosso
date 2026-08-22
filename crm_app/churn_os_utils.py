"""Utilitários de cruzamento O.S. entre Venda CRM e ImportacaoChurn."""

from __future__ import annotations

from typing import Any, Optional


def os_variantes(val: Optional[str]) -> set[str]:
    """Variantes da O.S. para match (com e sem zeros à esquerda)."""
    if val is None:
        return set()
    s = str(val).strip()
    if not s or s.upper() == 'NAN':
        return set()
    if s.endswith('.0'):
        s = s[:-2]
    out = {s}
    if s.isdigit():
        out.add(s.zfill(8))
        out.add(s.lstrip('0') or '0')
    if s.upper().startswith('OS-'):
        out.update(os_variantes(s[3:]))
    return {x for x in out if x}


def build_osab_documento_set(documentos) -> set[str]:
    """Conjunto de chaves OSAB (documento) com variantes para match com ordem_servico do CRM."""
    osab_set: set[str] = set()
    for doc in documentos:
        if doc is None:
            continue
        s = str(doc).strip()
        if not s or s.upper() == 'NAN':
            continue
        osab_set.update(os_variantes(s))
    return osab_set


def pedido_consta_no_osab(pedido: Optional[str], osab_set: set[str]) -> bool:
    if not osab_set or not pedido:
        return False
    return bool(os_variantes(str(pedido).strip()) & osab_set)


def rotulo_validacao_osab(pedido: Optional[str], osab_set: set[str]) -> str:
    """Retorno para exportações: CONSTA OSAB / NÃO CONSTA OSAB."""
    if pedido_consta_no_osab(pedido, osab_set):
        return 'CONSTA OSAB'
    return 'NÃO CONSTA OSAB'


def build_venda_lookup_por_os(vendas_qs) -> dict[str, Any]:
    """Mapeia variantes de ordem_servico -> instância Venda (primeira ocorrência)."""
    lookup: dict[str, Any] = {}
    for venda in vendas_qs.iterator(chunk_size=3000):
        os_val = (venda.ordem_servico or '').strip()
        if not os_val:
            continue
        for key in os_variantes(os_val):
            lookup.setdefault(key, venda)
    return lookup


def encontrar_venda_por_churn(churn, lookup: dict[str, Any]):
    """Localiza venda CRM a partir de numero_pedido / nr_ordem do churn."""
    for raw in (churn.numero_pedido, churn.nr_ordem):
        if not raw:
            continue
        for key in os_variantes(str(raw).strip()):
            v = lookup.get(key)
            if v:
                return v
    return None


def valor_planilha_churn(row, *nomes_coluna) -> Optional[str]:
    """Lê primeira coluna preenchida na linha da planilha churn."""
    import pandas as pd

    for nome in nomes_coluna:
        v = row.get(nome, '')
        if pd.notna(v) and str(v).strip() and str(v).strip().upper() != 'NAN':
            return str(v).strip()
    return None


def anomes_filtro_variantes(anomes: str) -> list[str]:
    """Aceita AAAAMM, AAAA-MM, AAAA/MM para filtro em CharField."""
    s = (anomes or '').strip().replace('-', '').replace('/', '')
    if len(s) == 6 and s.isdigit():
        y, m = int(s[:4]), int(s[4:6])
        return [s, f'{y}-{m:02d}', f'{y}/{m:02d}']
    return [anomes] if anomes else []
