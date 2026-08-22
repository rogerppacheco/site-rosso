"""
Mapeamento padronizado de status FPD para status interno do sistema.

Mapeamento de DS_STATUS_FATURA (do FPD) → STATUS NO CRM:
- Paga → Pago
- Paga_aguardando_repasse → Pago
- Aguardando_arrecadacao → Não Pago (ou Atrasado se vencido)
- Ajustada → Pago
- Erro_nao_recobravel → Não Pago (ou Atrasado se vencido)
- Emitida → Não Pago
- Baixa_por_acordo → Pago
- Cancelada / Cancelada_por_inadimplencia / Zerada → Outros

INDICADOR da planilha:
- FPD → 1ª fatura
- SPD → 2ª fatura
- TPD → 3ª fatura
"""
from __future__ import annotations

from datetime import date
from typing import Optional

# Mapeamento de DS_STATUS_FATURA (do FPD) para status interno do sistema
FPD_STATUS_MAP = {
    'PAGA': 'PAGO',
    'PAGA_AGUARDANDO_REPASSE': 'PAGO',
    'AGUARDANDO_ARRECADACAO': 'NAO_PAGO',
    'AJUSTADA': 'PAGO',
    'ERRO_NAO_RECOBRAVEL': 'NAO_PAGO',
    'EMITIDA': 'NAO_PAGO',
    'BAIXA_POR_ACORDO': 'PAGO',
    'CANCELADA': 'OUTROS',
    'CANCELADA_POR_INADIMPLENCIA': 'OUTROS',
    'ZERADA': 'OUTROS',
    # Variações / retrocompatibilidade
    'PAGO': 'PAGO',
    'NAO_PAGO': 'NAO_PAGO',
    'ABERTO': 'NAO_PAGO',
    'VENCIDO': 'ATRASADO',
    'AGUARDANDO': 'AGUARDANDO',
}

INDICADOR_PARA_NUMERO_FATURA = {
    'FPD': 1,
    'SPD': 2,
    'TPD': 3,
}

NUMERO_FATURA_PARA_INDICADOR = {v: k for k, v in INDICADOR_PARA_NUMERO_FATURA.items()}


def normalizar_indicador_fpd(indicador_raw) -> str:
    """Normaliza INDICADOR da planilha para FPD, SPD ou TPD (default FPD)."""
    if not indicador_raw:
        return 'FPD'
    valor = str(indicador_raw).strip().upper()
    if valor in ('FPD', 'SPD', 'TPD'):
        return valor
    # Fallbacks numéricos / texto
    if valor in ('1', '1A', 'PRIMEIRA', 'FIRST'):
        return 'FPD'
    if valor in ('2', '2A', 'SEGUNDA', 'SECOND'):
        return 'SPD'
    if valor in ('3', '3A', 'TERCEIRA', 'THIRD'):
        return 'TPD'
    return 'FPD'


def normalizar_status_fpd(status_str) -> str:
    """
    Normaliza um status vindo do FPD para o sistema interno.

    Returns:
        String com status normalizado (PAGO, NAO_PAGO, AGUARDANDO, ATRASADO, OUTROS)
    """
    if not status_str:
        return 'NAO_PAGO'

    status_normalizado = str(status_str).strip().upper().replace(' ', '_')
    return FPD_STATUS_MAP.get(status_normalizado, 'OUTROS')


def resolver_status_fatura_fpd(
    status_str,
    *,
    ds_sit_fatura: Optional[str] = None,
    data_vencimento: Optional[date] = None,
    dias_atraso: int = 0,
    hoje: Optional[date] = None,
) -> str:
    """
    Resolve status interno alinhado às filas do painel Qualidade.

    - PAGO / OUTROS (canceladas etc.) preservados.
    - Em aberto (ABERTA ou status de débito): ATRASADO se vencido; senão NAO_PAGO.
    """
    base = normalizar_status_fpd(status_str)
    if base == 'PAGO':
        return 'PAGO'
    if base == 'OUTROS':
        # Canceladas / zeradas: fora das filas de tratamento
        sit = (ds_sit_fatura or '').strip().upper()
        if sit == 'FECHADA':
            return 'OUTROS'

    sit = (ds_sit_fatura or '').strip().upper()
    hoje = hoje or date.today()
    vencido = False
    if data_vencimento and data_vencimento < hoje:
        vencido = True
    if dias_atraso and int(dias_atraso) > 0:
        vencido = True

    if sit == 'ABERTA' or base in ('NAO_PAGO', 'AGUARDANDO', 'ATRASADO'):
        if vencido:
            return 'ATRASADO'
        return 'NAO_PAGO' if base != 'AGUARDANDO' else 'AGUARDANDO'

    return base
