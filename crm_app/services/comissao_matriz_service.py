"""
Matriz de comissão: faixas (instaladas) × planos (colunas dinâmicas).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.utils import DatabaseError

from crm_app.comissao_folha_service import _plano_nome_to_banda
from crm_app.models import (
    ConfigComissaoVendedor,
    Plano,
    PlanoValoresComissaoVendedor,
    RegraComissaoFaixa,
    RegraComissaoFaixaPlano,
)

logger = logging.getLogger(__name__)


class MatrizComissaoCache:
    """Cache em memória faixa×plano e manual×plano — evita .get() por venda na folha."""

    def __init__(self) -> None:
        self._faixa_plano: dict[tuple[int, int], RegraComissaoFaixaPlano] = {}
        self._manual_config: dict[tuple[int, int], PlanoValoresComissaoVendedor] = {}

    @classmethod
    def carregar(cls, config_ids: list[int] | None = None) -> 'MatrizComissaoCache':
        inst = cls()
        try:
            for row in RegraComissaoFaixaPlano.objects.all():
                inst._faixa_plano[(row.faixa_id, row.plano_id)] = row
        except DatabaseError as exc:
            logger.warning(
                "[MATRIZ_CACHE] Matriz faixa×plano indisponível (%s) — fallback legado",
                exc,
            )
        try:
            qs_manual = PlanoValoresComissaoVendedor.objects.all()
            if config_ids:
                qs_manual = qs_manual.filter(config_id__in=config_ids)
            for row in qs_manual:
                inst._manual_config[(row.config_id, row.plano_id)] = row
        except DatabaseError as exc:
            logger.warning(
                "[MATRIZ_CACHE] Valores manuais por plano indisponíveis (%s) — fallback legado",
                exc,
            )
        return inst


def _decimal_or_none(val: Any) -> Decimal | None:
    if val is None or val == '':
        return None
    return Decimal(str(val))


def _legacy_valores_faixa_banda(faixa: RegraComissaoFaixa, banda: str) -> tuple[Decimal | None, Decimal | None]:
    from crm_app.comissao_folha_service import _banda_legado_comissao

    banda_ref = _banda_legado_comissao(banda)
    if banda_ref == '500MB':
        return faixa.valor_500mb_pap, faixa.valor_500mb_cnpj
    if banda_ref == '700MB':
        return faixa.valor_700mb_pap, faixa.valor_700mb_cnpj
    if banda_ref == '1GB':
        return faixa.valor_1gb_pap, faixa.valor_1gb_cnpj
    return None, None


def get_valor_faixa_plano(
    faixa: RegraComissaoFaixa | None,
    plano: Plano | None,
    tipo_cliente: str,
    matriz_cache: MatrizComissaoCache | None = None,
) -> float | None:
    """Valor na interseção faixa × plano; fallback nas colunas legadas 500/700/1GB."""
    if not faixa or not plano:
        return None
    faixa_id = getattr(faixa, 'id', None)
    plano_id = getattr(plano, 'id', None)
    row: RegraComissaoFaixaPlano | None = None
    if matriz_cache is not None:
        if isinstance(faixa_id, int) and isinstance(plano_id, int):
            row = matriz_cache._faixa_plano.get((faixa_id, plano_id))
    elif isinstance(faixa_id, int) and isinstance(plano_id, int):
        try:
            row = RegraComissaoFaixaPlano.objects.get(faixa_id=faixa_id, plano_id=plano_id)
        except RegraComissaoFaixaPlano.DoesNotExist:
            row = None
    if row is not None:
        if tipo_cliente == 'CPF' and row.valor_pap is not None:
            return float(row.valor_pap)
        if tipo_cliente == 'CNPJ' and row.valor_cnpj is not None:
            return float(row.valor_cnpj)
    banda = _plano_nome_to_banda(plano.nome)
    if not banda:
        return None
    pap, cnpj = _legacy_valores_faixa_banda(faixa, banda)
    if tipo_cliente == 'CPF' and pap is not None:
        return float(pap)
    if tipo_cliente == 'CNPJ' and cnpj is not None:
        return float(cnpj)
    return None


def get_valor_manual_vendedor_plano(
    config: ConfigComissaoVendedor | None,
    plano: Plano | None,
    tipo_cliente: str,
    matriz_cache: MatrizComissaoCache | None = None,
) -> float | None:
    if not config or not plano:
        return None
    config_id = getattr(config, 'id', None)
    plano_id = getattr(plano, 'id', None)
    row: PlanoValoresComissaoVendedor | None = None
    if matriz_cache is not None:
        if isinstance(config_id, int) and isinstance(plano_id, int):
            row = matriz_cache._manual_config.get((config_id, plano_id))
    elif isinstance(config_id, int) and isinstance(plano_id, int):
        try:
            row = PlanoValoresComissaoVendedor.objects.get(config_id=config_id, plano_id=plano_id)
        except PlanoValoresComissaoVendedor.DoesNotExist:
            row = None
    if row is None:
        return None
    if tipo_cliente == 'CPF' and row.valor_pap is not None:
        return float(row.valor_pap)
    if tipo_cliente == 'CNPJ' and row.valor_cnpj is not None:
        return float(row.valor_cnpj)
    return None


@transaction.atomic
def sincronizar_plano_em_todas_faixas(plano: Plano) -> int:
    """Garante célula (faixa × plano) para cada faixa existente ao cadastrar plano."""
    count = 0
    banda = _plano_nome_to_banda(plano.nome)
    for faixa in RegraComissaoFaixa.objects.all():
        pap, cnpj = _legacy_valores_faixa_banda(faixa, banda) if banda else (None, None)
        _, created = RegraComissaoFaixaPlano.objects.get_or_create(
            faixa=faixa,
            plano=plano,
            defaults={'valor_pap': pap, 'valor_cnpj': cnpj},
        )
        if created:
            count += 1
    return count


@transaction.atomic
def sincronizar_todos_planos_em_faixas() -> int:
    """Preenche matriz faixa×plano para todos os planos ativos (migração/rotina)."""
    total = 0
    for plano in Plano.objects.filter(ativo=True):
        total += sincronizar_plano_em_todas_faixas(plano)
    return total


def listar_matriz_comissao() -> dict[str, Any]:
    planos = list(
        Plano.objects.filter(ativo=True)
        .select_related('operadora')
        .order_by('nome')
    )
    faixas_qs = (
        RegraComissaoFaixa.objects.select_related('vendedor')
        .prefetch_related('valores_por_plano')
        .order_by('perfil', 'vendedor', 'min_vendas')
    )
    plano_ids = [p.id for p in planos]
    faixas_out: list[dict[str, Any]] = []
    for faixa in faixas_qs:
        valores_map: dict[str, dict[str, float | None]] = {}
        for vp in faixa.valores_por_plano.all():
            if vp.plano_id not in plano_ids:
                continue
            valores_map[str(vp.plano_id)] = {
                'valor_pap': float(vp.valor_pap) if vp.valor_pap is not None else None,
                'valor_cnpj': float(vp.valor_cnpj) if vp.valor_cnpj is not None else None,
            }
        for plano in planos:
            key = str(plano.id)
            if key not in valores_map:
                pap, cnpj = _legacy_valores_faixa_banda(
                    faixa, _plano_nome_to_banda(plano.nome) or '',
                )
                valores_map[key] = {
                    'valor_pap': float(pap) if pap is not None else None,
                    'valor_cnpj': float(cnpj) if cnpj is not None else None,
                }
        faixas_out.append({
            'id': faixa.id,
            'perfil': faixa.perfil,
            'vendedor_id': faixa.vendedor_id,
            'vendedor_username': faixa.vendedor.username if faixa.vendedor_id else None,
            'finalidade': faixa.finalidade,
            'faixa_nome': faixa.faixa_nome,
            'min_vendas': faixa.min_vendas,
            'max_vendas': faixa.max_vendas,
            'valores_por_plano': valores_map,
        })
    return {
        'planos': [
            {
                'id': p.id,
                'nome': p.nome,
                'operadora_nome': p.operadora.nome if p.operadora_id else '',
            }
            for p in planos
        ],
        'faixas': faixas_out,
    }


@transaction.atomic
def salvar_matriz_comissao(payload: dict[str, Any]) -> dict[str, int]:
    """
    Persiste células e metadados de faixas.
    payload: { faixas: [{ id?, perfil, faixa_nome, min_vendas, max_vendas, finalidade, vendedor, valores_por_plano }] }
    """
    atualizadas = 0
    criadas_faixas = 0
    for row in payload.get('faixas') or []:
        faixa_id = row.get('id')
        dados_faixa = {
            'perfil': row.get('perfil') or None,
            'vendedor_id': row.get('vendedor') or row.get('vendedor_id') or None,
            'finalidade': row.get('finalidade') or 'COMISSAO',
            'faixa_nome': row.get('faixa_nome') or '',
            'min_vendas': int(row.get('min_vendas') or 0),
            'max_vendas': int(row.get('max_vendas') if row.get('max_vendas') is not None else 99999),
        }
        if faixa_id:
            faixa = RegraComissaoFaixa.objects.get(pk=faixa_id)
            for campo, valor in dados_faixa.items():
                setattr(faixa, campo, valor)
            faixa.save()
        else:
            faixa = RegraComissaoFaixa.objects.create(**dados_faixa)
            criadas_faixas += 1
            for plano in Plano.objects.filter(ativo=True):
                RegraComissaoFaixaPlano.objects.get_or_create(faixa=faixa, plano=plano)

        for plano_id_str, vals in (row.get('valores_por_plano') or {}).items():
            plano_id = int(plano_id_str)
            vp, _ = RegraComissaoFaixaPlano.objects.get_or_create(faixa=faixa, plano_id=plano_id)
            vp.valor_pap = _decimal_or_none(vals.get('valor_pap'))
            vp.valor_cnpj = _decimal_or_none(vals.get('valor_cnpj'))
            vp.save(update_fields=['valor_pap', 'valor_cnpj'])
            atualizadas += 1
    return {'celulas': atualizadas, 'faixas_criadas': criadas_faixas}


def listar_valores_manuais_vendedor(config: ConfigComissaoVendedor) -> list[dict[str, Any]]:
    """
    Monta a grade de valores manuais por plano para o vendedor.

    Inclui:
    - todos os planos ativos (novos entram automaticamente);
    - planos inativos que já tenham valor salvo nesta config (histórico).
    """
    existentes = {
        v.plano_id: v
        for v in PlanoValoresComissaoVendedor.objects.filter(config=config).select_related(
            'plano', 'plano__operadora',
        )
    }
    planos_ativos = list(
        Plano.objects.filter(ativo=True).select_related('operadora').order_by('nome')
    )
    ids_ativos = {p.id for p in planos_ativos}

    out: list[dict[str, Any]] = []
    for plano in planos_ativos:
        row = existentes.get(plano.id)
        out.append({
            'plano_id': plano.id,
            'plano_nome': plano.nome,
            'plano_ativo': True,
            'operadora_nome': plano.operadora.nome if plano.operadora_id else None,
            'valor_pap': float(row.valor_pap) if row and row.valor_pap is not None else None,
            'valor_cnpj': float(row.valor_cnpj) if row and row.valor_cnpj is not None else None,
        })

    inativos_com_valor: list[tuple[Plano, PlanoValoresComissaoVendedor]] = []
    for plano_id, row in existentes.items():
        if plano_id in ids_ativos:
            continue
        plano = row.plano
        if not plano or plano.ativo:
            continue
        # Só reaparece inativo se já houver valor manual preenchido (histórico útil).
        if row.valor_pap is None and row.valor_cnpj is None:
            continue
        inativos_com_valor.append((plano, row))

    inativos_com_valor.sort(key=lambda item: (item[0].nome or '').upper())
    for plano, row in inativos_com_valor:
        out.append({
            'plano_id': plano.id,
            'plano_nome': plano.nome,
            'plano_ativo': bool(plano.ativo),
            'operadora_nome': plano.operadora.nome if getattr(plano, 'operadora_id', None) else None,
            'valor_pap': float(row.valor_pap) if row.valor_pap is not None else None,
            'valor_cnpj': float(row.valor_cnpj) if row.valor_cnpj is not None else None,
        })
    return out


@transaction.atomic
def salvar_valores_manuais_vendedor(
    config: ConfigComissaoVendedor,
    valores: list[dict[str, Any]],
) -> int:
    count = 0
    for item in valores:
        plano_id = item.get('plano_id') or item.get('plano')
        if not plano_id:
            continue
        vp, _ = PlanoValoresComissaoVendedor.objects.get_or_create(
            config=config, plano_id=plano_id,
        )
        vp.valor_pap = _decimal_or_none(item.get('valor_pap'))
        vp.valor_cnpj = _decimal_or_none(item.get('valor_cnpj'))
        vp.save(update_fields=['valor_pap', 'valor_cnpj'])
        count += 1
    return count
