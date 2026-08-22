# -*- coding: utf-8 -*-
"""
Lookup CEP -> município (cidade) com cache persistente e múltiplas fontes.
Ordem: cache memória -> banco local (CepLocalidade) -> cache arquivo -> ViaCEP -> OpenCEP.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_CACHE_PATH = None
_FILE_CACHE = {}
_FILE_CACHE_LOADED = False


def _get_cache_path():
    global _CACHE_PATH
    if _CACHE_PATH is None:
        _CACHE_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data',
            'cep_localidade_cache.json'
        )
    return _CACHE_PATH


def _load_file_cache():
    global _FILE_CACHE, _FILE_CACHE_LOADED
    if _FILE_CACHE_LOADED:
        return
    _FILE_CACHE_LOADED = True
    path = _get_cache_path()
    if not os.path.isfile(path):
        _FILE_CACHE = {}
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            _FILE_CACHE = {k: v for k, v in data.items() if v}
        else:
            _FILE_CACHE = {}
    except Exception as e:
        logger.warning('[CEP lookup] Erro ao carregar cache de CEP: %s', e)
        _FILE_CACHE = {}


def _save_file_cache():
    path = _get_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(_FILE_CACHE, f, ensure_ascii=False)
    except Exception as e:
        logger.warning('[CEP lookup] Erro ao salvar cache de CEP: %s', e)


def _consultar_banco(cep_limpo):
    """Consulta tabela CepLocalidade no banco; retorna localidade ou None."""
    try:
        from crm_app.models import CepLocalidade
        row = CepLocalidade.objects.filter(cep=cep_limpo).values_list('localidade', flat=True).first()
        return (row or '').strip() or None
    except Exception as e:
        logger.debug('[CEP lookup] Banco CepLocalidade erro para %s: %s', cep_limpo, e)
        return None


def _consultar_viacep(cep_limpo):
    """Consulta ViaCEP; retorna localidade ou None."""
    try:
        from .viacep import consultar_cep
        res = consultar_cep(cep_limpo, cache=None)
        return (res.get('localidade') or '').strip() or None
    except Exception as e:
        logger.debug('[CEP lookup] ViaCEP erro para %s: %s', cep_limpo, e)
        return None


def _consultar_opencep(cep_limpo):
    """Consulta OpenCEP (gratuito, sem token); retorna localidade ou None."""
    try:
        import urllib.request
        url = f"https://opencep.com/v1/{cep_limpo}.json"
        req = urllib.request.Request(url, headers={'User-Agent': 'RecordCRM/1.0'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if isinstance(data, dict) and data.get('localidade'):
            return (data.get('localidade') or '').strip() or None
    except Exception as e:
        logger.debug('[CEP lookup] OpenCEP erro para %s: %s', cep_limpo, e)
    return None


def get_municipio_por_cep(cep, cache=None, persist=True, db_dict=None):
    """
    Retorna o nome do município (cidade) para o CEP.

    Ordem: cache em memória (passado) -> banco (CepLocalidade ou db_dict) -> cache em arquivo -> ViaCEP -> OpenCEP.
    Quando encontra em API, salva no cache em arquivo (se persist=True).

    Args:
        cep: CEP (str ou int, com ou sem formatação)
        cache: dict opcional {cep_limpo: localidade} para evitar repetição na mesma requisição
        persist: se True, grava novos resultados da API em crm_app/data/cep_localidade_cache.json
        db_dict: dict opcional {cep_limpo: localidade} para usar em vez de consultar o banco (evita N queries em importação)

    Returns:
        Nome do município ou None.
    """
    cep_limpo = re.sub(r'\D', '', str(cep or ''))
    if len(cep_limpo) != 8:
        return None

    if cache is not None and cep_limpo in cache:
        return cache[cep_limpo]

    if db_dict is not None:
        nome = db_dict.get(cep_limpo)
        if nome:
            if cache is not None:
                cache[cep_limpo] = nome
            return (nome or '').strip() or None
    else:
        nome = _consultar_banco(cep_limpo)
        if nome:
            if cache is not None:
                cache[cep_limpo] = nome
            return nome

    _load_file_cache()
    if cep_limpo in _FILE_CACHE:
        nome = _FILE_CACHE[cep_limpo]
        if cache is not None:
            cache[cep_limpo] = nome
        return nome

    nome = _consultar_viacep(cep_limpo)
    if not nome:
        nome = _consultar_opencep(cep_limpo)

    if nome and persist:
        _FILE_CACHE[cep_limpo] = nome
        _save_file_cache()
    if cache is not None:
        cache[cep_limpo] = nome
    return nome


def get_cache_stats():
    """Retorna quantidade de CEPs no cache persistente (para diagnóstico)."""
    _load_file_cache()
    return len(_FILE_CACHE)
