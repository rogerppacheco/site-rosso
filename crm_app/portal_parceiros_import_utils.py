"""Normalização de colunas para planilhas Portal Parceiros (FPD e OSAB)."""

from __future__ import annotations

import unicodedata
from typing import Optional

import pandas as pd


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize('NFD', str(text))
    return ''.join(ch for ch in normalized if unicodedata.category(ch) != 'Mn')


def normalizar_header(col, *, uppercase: bool = True) -> str:
    s = strip_accents(str(col).strip()).replace(' ', '_')
    return s.upper() if uppercase else s.lower()


def normalizar_colunas_dataframe(df: pd.DataFrame, *, uppercase: bool = True) -> pd.DataFrame:
    out = df.copy()
    out.columns = [normalizar_header(c, uppercase=uppercase) for c in out.columns]
    return out


def aplicar_aliases_colunas(
    df: pd.DataFrame,
    aliases: dict[str, str],
    *,
    uppercase: bool = True,
) -> pd.DataFrame:
    """Renomeia colunas conforme aliases (nomes canônicos do sistema)."""
    out = df.copy()
    mapa = {
        normalizar_header(origem, uppercase=uppercase): destino.upper() if uppercase else destino.lower()
        for origem, destino in aliases.items()
    }
    rename: dict[str, str] = {}
    for col in out.columns:
        destino = mapa.get(col)
        if destino and destino != col and destino not in rename.values():
            rename[col] = destino
    if rename:
        out = out.rename(columns=rename)
    return out


# Layout legado OSAB → nomes internos do ImportacaoOsabView
OSAB_ALIASES = {
    'NR_ORDEM': 'PEDIDO',
    'DATA_HORA_ATUALIZACAO': 'DT_REF',
    'STATUS': 'SITUACAO',
    'MUNICIPIO': 'LOCALIDADE',
    'VELOCIDADE_MBPS': 'VELOCIDADE',
    'METODO_PGTO': 'MEIO_PAGAMENTO',
    'MATRICULA_VENDEDOR': 'MATRICULA_VENDEDOR',
    'SAP': 'PDV_SAP',
    'NR_BA': 'NUMERO_BA',
    'CRIACAO_BA': 'DATA_ABERTURA',
    'PENDENCIA': 'COD_PENDENCIA',
    'MOTIVO_ORDEM': 'DESC_MOTIVO_ORDEM',
    'SUB_MOTIVO_ORDEM': 'DESC_SUB_MOTIVO_ORDEM',
    'PLANO': 'CLASSE_PRODUTO',
    'DATA_ATIVACAO': 'DATA_FECHAMENTO',
    'REDE': 'CD_REDE',
    'INICIO_EXECUCAO_REAL': 'DATA_AGENDAMENTO',
}

OSAB_PEDIDO_FALLBACKS = ('NR_ORDEM', 'NR_ORDEM_ORIGINAL', 'NUMERO_BA')

# Layout Portal Parceiros FPD → nomes internos do ImportarFPDView
FPD_ALIASES = {
    'nr_ordem_venda': 'nr_ordem',
    'status_pag': 'ds_status_fatura',
}

FPD_COLUNAS_TEXTO = (
    'ID_CONTRATO',
    'NR_FATURA',
    'NR_ORDEM',
    'NR_ORDEM_VENDA',
)


def coluna_tem_valores(df: pd.DataFrame, col_nome: str) -> bool:
    if col_nome not in df.columns:
        return False
    serie = df[col_nome].astype(str).str.replace('nan', '', regex=False).str.strip()
    return serie.ne('').any()


def resolver_coluna_pedido_osab(df: pd.DataFrame) -> pd.DataFrame:
    """Garante coluna PEDIDO a partir de aliases/fallbacks do Portal Parceiros."""
    out = df.copy()
    if coluna_tem_valores(out, 'PEDIDO'):
        return out
    for alt_col in OSAB_PEDIDO_FALLBACKS:
        if coluna_tem_valores(out, alt_col):
            out['PEDIDO'] = out[alt_col]
            break
    return out


def normalizar_colunas_osab(df: pd.DataFrame) -> pd.DataFrame:
    out = normalizar_colunas_dataframe(df, uppercase=True)
    out = aplicar_aliases_colunas(out, OSAB_ALIASES, uppercase=True)
    out = resolver_coluna_pedido_osab(out)
    return out


def normalizar_colunas_fpd(df: pd.DataFrame) -> pd.DataFrame:
    out = normalizar_colunas_dataframe(df, uppercase=False)
    return aplicar_aliases_colunas(out, FPD_ALIASES, uppercase=False)


def coluna_nr_ordem_fpd_presente(df: pd.DataFrame) -> bool:
    return 'nr_ordem' in df.columns


def extrair_vl_fatura_fpd(row) -> float:
    """Portal Parceiros não traz VL_FATURA; default explícito zero."""
    val = row.get('vl_fatura') if hasattr(row, 'get') else None
    if val is None or pd.isna(val):
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def extrair_indicador_fpd(row) -> Optional[str]:
    """INDICADOR da planilha (coluna G): FPD, SPD, TPD."""
    val = row.get('indicador') if hasattr(row, 'get') else None
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().upper()
    return s or None
