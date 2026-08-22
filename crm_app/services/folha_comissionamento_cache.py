"""
Cache da folha de comissionamento — evita recalcular ~85s a cada requisição.

Usa versionamento por mês: ao fechar/reabrir pagamento, incrementa a versão
e entradas antigas expiram pelo TTL sem delete em massa.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_VERSION_KEY = "folha_comissao_ver:{ano}:{mes}"
# v2: linhas 600MB e 600MB Cidade Especial separadas do 500MB
_FOLHA_SCHEMA = 2
_DATA_KEY = "folha_comissao:s{schema}:{ano}:{mes}:{vendedor_id}:{use_effective}:{version}"


def _cache_ttl() -> int:
    return int(getattr(settings, "FOLHA_COMISSAO_CACHE_TTL", 1800))


def _cache_enabled() -> bool:
    return bool(getattr(settings, "FOLHA_COMISSAO_CACHE_ENABLED", True))


def _version_key(ano: int, mes: int) -> str:
    return _VERSION_KEY.format(ano=ano, mes=mes)


def _data_key(
    ano: int,
    mes: int,
    vendedor_id: Optional[int],
    use_effective_date: bool,
    version: int,
) -> str:
    vid = vendedor_id if vendedor_id is not None else "all"
    return _DATA_KEY.format(
        schema=_FOLHA_SCHEMA,
        ano=ano,
        mes=mes,
        vendedor_id=vid,
        use_effective=int(use_effective_date),
        version=version,
    )


def obter_versao_cache(ano: int, mes: int) -> int:
    """Versão atual do cache para o mês (0 = primeira geração)."""
    return int(cache.get(_version_key(ano, mes), 0))


def invalidar_folha_mes(ano: int, mes: int) -> None:
    """Invalida todas as entradas do mês incrementando a versão."""
    key = _version_key(ano, mes)
    nova = obter_versao_cache(ano, mes) + 1
    cache.set(key, nova, timeout=None)
    logger.info("[FOLHA_CACHE] Versão do mês %02d/%d atualizada para %s", mes, ano, nova)


def invalidar_folha_por_data(data: Any) -> None:
    """Invalida cache da folha do mês da data informada (lançamentos manuais)."""
    if data is None:
        return
    try:
        if hasattr(data, "year") and hasattr(data, "month"):
            ano, mes = int(data.year), int(data.month)
        else:
            from datetime import date as date_cls

            parsed = date_cls.fromisoformat(str(data)[:10])
            ano, mes = parsed.year, parsed.month
        if 1 <= mes <= 12:
            invalidar_folha_mes(ano, mes)
    except (TypeError, ValueError, AttributeError):
        logger.warning("[FOLHA_CACHE] Não foi possível invalidar cache para data=%s", data)


def obter_folha_cacheada(
    ano: int,
    mes: int,
    vendedor_id: Optional[int],
    use_effective_date: bool,
) -> Optional[dict[str, Any]]:
    """Retorna folha do cache ou None se ausente/desabilitado."""
    if not _cache_enabled():
        return None
    version = obter_versao_cache(ano, mes)
    key = _data_key(ano, mes, vendedor_id, use_effective_date, version)
    dados = cache.get(key)
    if dados is not None:
        logger.info(
            "[FOLHA_CACHE] Hit ano=%s mes=%s vendedor=%s effective=%s v=%s",
            ano,
            mes,
            vendedor_id,
            use_effective_date,
            version,
        )
    return dados


def salvar_folha_cache(
    ano: int,
    mes: int,
    vendedor_id: Optional[int],
    use_effective_date: bool,
    dados: dict[str, Any],
) -> None:
    """Persiste folha calculada no cache."""
    if not _cache_enabled():
        return
    version = obter_versao_cache(ano, mes)
    key = _data_key(ano, mes, vendedor_id, use_effective_date, version)
    cache.set(key, dados, timeout=_cache_ttl())
    logger.info(
        "[FOLHA_CACHE] Miss — salvo ano=%s mes=%s vendedor=%s effective=%s v=%s ttl=%ss",
        ano,
        mes,
        vendedor_id,
        use_effective_date,
        version,
        _cache_ttl(),
    )


def calcular_folha_mes_com_cache(
    ano: int,
    mes: int,
    vendedor_id: Optional[int] = None,
    use_effective_date_for_display: bool = False,
) -> dict[str, Any]:
    """Wrapper com cache sobre calcular_folha_mes."""
    cached = obter_folha_cacheada(ano, mes, vendedor_id, use_effective_date_for_display)
    if cached is not None:
        return cached

    from crm_app.comissao_folha_service import calcular_folha_mes

    dados = calcular_folha_mes(
        ano,
        mes,
        vendedor_id,
        use_effective_date_for_display=use_effective_date_for_display,
    )
    salvar_folha_cache(ano, mes, vendedor_id, use_effective_date_for_display, dados)
    return dados
