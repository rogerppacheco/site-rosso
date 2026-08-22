"""
Rate limiting via DatabaseCache (sem Redis, sem custo).
"""
from __future__ import annotations

import time
from typing import Optional

from django.core.cache import cache


def permitir_requisicao(
    chave: str,
    max_chamadas: int,
    periodo_segundos: int,
) -> tuple[bool, Optional[int]]:
    """
    Retorna (permitido, segundos_para_retry).
    Sliding window simplificado em cache.
    """
    cache_key = f"rate_limit:{chave}"
    agora = time.time()
    dados = cache.get(cache_key)

    if not dados or agora - dados.get("inicio", 0) >= periodo_segundos:
        cache.set(cache_key, {"inicio": agora, "contagem": 1}, periodo_segundos)
        return True, None

    contagem = int(dados.get("contagem", 0))
    if contagem >= max_chamadas:
        retry = int(periodo_segundos - (agora - dados["inicio"])) + 1
        return False, max(retry, 1)

    dados["contagem"] = contagem + 1
    ttl_restante = int(periodo_segundos - (agora - dados["inicio"])) or periodo_segundos
    cache.set(cache_key, dados, ttl_restante)
    return True, None
