# -*- coding: utf-8 -*-
"""
Consulta de endereço por CEP com fallback ViaCEP -> OpenCEP.
Usado pelo proxy da API (CRM vendas, CDOI, etc.).
"""
import logging
import re
from typing import Any, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_HEADERS = {'User-Agent': 'RecordCRM/1.0'}
_TIMEOUT = 10


def normalizar_cep(cep) -> str:
    return re.sub(r'\D', '', str(cep or ''))


def cep_resposta_tem_erro(data: Any) -> bool:
    """ViaCEP retorna erro como boolean true ou string \"true\"."""
    if not isinstance(data, dict):
        return True
    erro = data.get('erro')
    if erro is True:
        return True
    if isinstance(erro, str) and erro.strip().lower() == 'true':
        return True
    return False


def _formatar_cep(cep_limpo: str) -> str:
    return f'{cep_limpo[:5]}-{cep_limpo[5:]}'


def _normalizar_endereco(data: dict, fonte: str) -> dict:
    cep_raw = str(data.get('cep') or '')
    cep_limpo = normalizar_cep(cep_raw)
    if cep_limpo and '-' not in cep_raw:
        cep_exibicao = _formatar_cep(cep_limpo)
    else:
        cep_exibicao = cep_raw or ( _formatar_cep(cep_limpo) if len(cep_limpo) == 8 else '')

    out = {
        'cep': cep_exibicao,
        'logradouro': (data.get('logradouro') or '').strip(),
        'complemento': (data.get('complemento') or '').strip(),
        'unidade': (data.get('unidade') or '').strip(),
        'bairro': (data.get('bairro') or '').strip(),
        'localidade': (data.get('localidade') or '').strip(),
        'uf': (data.get('uf') or '').strip()[:2],
        'ibge': data.get('ibge') or '',
        'gia': data.get('gia') or '',
        'ddd': data.get('ddd') or '',
        'siafi': data.get('siafi') or '',
        'estado': data.get('estado') or '',
        'regiao': data.get('regiao') or '',
        '_fonte': fonte,
    }
    return out


def _endereco_valido(data: dict) -> bool:
    return bool((data.get('logradouro') or data.get('localidade')) and data.get('uf'))


def _consultar_viacep(cep_limpo: str) -> Tuple[Optional[dict], Optional[str]]:
    url = f'https://viacep.com.br/ws/{cep_limpo}/json/'
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return None, 'timeout'
    except requests.exceptions.RequestException as e:
        return None, f'rede:{e}'
    except ValueError:
        return None, 'json_invalido'

    if cep_resposta_tem_erro(data):
        return None, 'not_found'
    normalized = _normalizar_endereco(data, 'viacep')
    if not _endereco_valido(normalized):
        return None, 'vazio'
    return normalized, None


def _consultar_opencep(cep_limpo: str) -> Tuple[Optional[dict], Optional[str]]:
    url = f'https://opencep.com/v1/{cep_limpo}.json'
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None, 'not_found'
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return None, 'timeout'
    except requests.exceptions.RequestException as e:
        return None, f'rede:{e}'
    except ValueError:
        return None, 'json_invalido'

    if cep_resposta_tem_erro(data):
        return None, 'not_found'
    normalized = _normalizar_endereco(data, 'opencep')
    if not _endereco_valido(normalized):
        return None, 'vazio'
    return normalized, None


def consultar_endereco_cep(cep: str) -> dict:
    """
    Consulta endereço por CEP (ViaCEP, depois OpenCEP).

    Retorna dict com status: ok | not_found | unavailable | invalid
    """
    cep_limpo = normalizar_cep(cep)
    if len(cep_limpo) != 8:
        return {'status': 'invalid'}

    viacep_data, viacep_err = _consultar_viacep(cep_limpo)
    if viacep_data:
        return {'status': 'ok', 'data': viacep_data, 'fonte': 'viacep'}

    opencep_data, opencep_err = _consultar_opencep(cep_limpo)
    if opencep_data:
        logger.info(
            '[CEP] %s atendido via OpenCEP (ViaCEP: %s)',
            cep_limpo,
            viacep_err or 'falhou',
        )
        return {'status': 'ok', 'data': opencep_data, 'fonte': 'opencep'}

    if viacep_err == 'not_found' and opencep_err == 'not_found':
        return {'status': 'not_found'}

    return {
        'status': 'unavailable',
        'detail': f'viacep={viacep_err or "?"}; opencep={opencep_err or "?"}',
    }
