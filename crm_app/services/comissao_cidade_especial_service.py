"""Comissão diferenciada para vendas em cidades de oferta especial."""
from __future__ import annotations

from typing import Iterable

from crm_app.models import CidadeOfertaEspecial, Plano, PlanoValoresComissao
from crm_app.services.gdp_preco_service import normalizar_municipio

CidadeEspecialCache = set[tuple[str, str]]


def carregar_cidades_oferta_especial() -> CidadeEspecialCache:
    """Carrega pares (UF, município normalizado) ativos para lookup O(1) na folha."""
    return {
        (uf, municipio)
        for uf, municipio in CidadeOfertaEspecial.objects.filter(ativo=True).values_list(
            'uf', 'municipio_normalizado',
        )
    }


def cidade_em_oferta_especial(
    cidade: str | None,
    estado: str | None,
    cache: CidadeEspecialCache | None = None,
) -> bool:
    """Indica se município/UF pertence à lista de oferta especial."""
    uf = (estado or '').strip().upper()[:2]
    municipio = normalizar_municipio(cidade or '')
    if not uf or not municipio:
        return False
    conjunto = cache if cache is not None else carregar_cidades_oferta_especial()
    return (uf, municipio) in conjunto


def venda_em_cidade_oferta_especial(
    venda,
    cache: CidadeEspecialCache | None = None,
) -> bool:
    """Atalho usando cidade/estado da venda."""
    if venda is None:
        return False
    return cidade_em_oferta_especial(
        getattr(venda, 'cidade', None),
        getattr(venda, 'estado', None),
        cache=cache,
    )


def _valores_comissao_plano(plano: Plano | None) -> PlanoValoresComissao | None:
    if not plano:
        return None
    try:
        return plano.valores_comissao
    except (PlanoValoresComissao.DoesNotExist, AttributeError):
        return None


def get_valor_comissao_cidade_especial(
    plano: Plano | None,
    tipo_cliente: str,
) -> float | None:
    """
    Valor fixo cadastrado no plano para cidade especial (PAP/CNPJ).

    Retorna None se o plano não estiver configurado para essa regra.
    """
    vc = _valores_comissao_plano(plano)
    if not vc or vc.usa_comissao_cidade_especial is not True:
        return None
    tipo = (tipo_cliente or '').strip().upper()
    if tipo == 'CPF' and vc.valor_pap_cidade_especial is not None:
        return float(vc.valor_pap_cidade_especial)
    if tipo == 'CNPJ' and vc.valor_cnpj_cidade_especial is not None:
        return float(vc.valor_cnpj_cidade_especial)
    # Se só um dos lados estiver preenchido, reutiliza (tabela atual é valor único).
    if vc.valor_pap_cidade_especial is not None:
        return float(vc.valor_pap_cidade_especial)
    if vc.valor_cnpj_cidade_especial is not None:
        return float(vc.valor_cnpj_cidade_especial)
    return None


def resolver_valor_cidade_especial(
    plano: Plano | None,
    tipo_cliente: str,
    *,
    venda=None,
    cache: CidadeEspecialCache | None = None,
) -> float | None:
    """
    Resolve comissão especial quando a venda está em cidade de oferta
    e o plano tem valor fixo cadastrado.
    """
    if venda is None:
        return None
    valor = get_valor_comissao_cidade_especial(plano, tipo_cliente)
    if valor is None:
        return None
    if not venda_em_cidade_oferta_especial(venda, cache=cache):
        return None
    return valor


def _grafia_municipio(municipio: str) -> str:
    """Normaliza grafia de exibição quando a fonte vem em caixa alta."""
    texto = (municipio or '').strip()
    if texto.isupper():
        return texto.title()
    return texto


def upsert_cidades_oferta_especial(
    pares: Iterable[tuple[str, str]],
    *,
    ativar: bool = True,
) -> dict[str, int]:
    """
    Cria/atualiza municípios a partir de pares (UF, município).

    Retorna contadores: criados, atualizados, ignorados.
    """
    criados = 0
    atualizados = 0
    ignorados = 0
    for uf_bruto, municipio_bruto in pares:
        uf = (uf_bruto or '').strip().upper()[:2]
        municipio = (municipio_bruto or '').strip()
        if not uf or not municipio:
            ignorados += 1
            continue
        municipio_norm = normalizar_municipio(municipio)
        grafia = _grafia_municipio(municipio)
        _obj, created = CidadeOfertaEspecial.objects.update_or_create(
            uf=uf,
            municipio_normalizado=municipio_norm,
            defaults={
                'municipio': grafia,
                'ativo': ativar,
            },
        )
        if created:
            criados += 1
        else:
            atualizados += 1
    return {'criados': criados, 'atualizados': atualizados, 'ignorados': ignorados}
