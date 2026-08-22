# -*- coding: utf-8 -*-
"""
Consulta ViaCEP para obter endereço (logradouro, bairro, cidade, UF) a partir do CEP.
Usado como fallback quando o município não é encontrado pelo código IBGE.
"""
import logging
import re

logger = logging.getLogger(__name__)


def consultar_cep(cep, cache=None):
    """
    Consulta ViaCEP e retorna localidade (cidade) e UF.

    Args:
        cep: CEP (str ou int, com ou sem formatação)
        cache: dict opcional {cep_limpo: {'localidade': str, 'uf': str}} para evitar chamadas repetidas

    Returns:
        dict com 'localidade' e 'uf', ou None se não encontrar/erro.
    """
    cep_limpo = re.sub(r'\D', '', str(cep or ''))
    if len(cep_limpo) != 8:
        return None

    if cache is not None and cep_limpo in cache:
        return cache[cep_limpo]

    try:
        import urllib.request
        url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
        req = urllib.request.Request(url, headers={'User-Agent': 'RecordCRM/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        logger.debug("[ViaCEP] Erro ao consultar CEP %s: %s", cep_limpo, e)
        result = None
    else:
        from .cep_endereco import cep_resposta_tem_erro
        if isinstance(data, dict) and not cep_resposta_tem_erro(data):
            result = {
                'localidade': (data.get('localidade') or '').strip(),
                'uf': (data.get('uf') or '').strip()[:2],
            }
            if not result['localidade'] and not result['uf']:
                result = None
        else:
            result = None

    if cache is not None:
        cache[cep_limpo] = result
    return result


def get_municipio_por_cep(cep, cache=None):
    """
    Retorna o nome do município (cidade) para o CEP, ou None.
    Usa ViaCEP como fonte. Útil quando codigo_municipio não está disponível ou lookup IBGE falha.
    """
    res = consultar_cep(cep, cache=cache)
    return res.get('localidade') if res else None
