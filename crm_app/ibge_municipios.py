# -*- coding: utf-8 -*-
"""
Lookup de nome de município por código IBGE (7 dígitos).
Usado para enriquecer a base CNPJ (Receita Federal) que só traz codigo_municipio.
Carrega da API do IBGE ou de arquivo estático (crm_app/data/ibge_municipios.json).
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_IBGE_MAP = None
_IBGE_MAP_LOADED = False
# Índice opcional: 6 dígitos (2 UF + 4 mun) -> nome, para códigos Receita de 4 dígitos
_IBGE_MAP_6 = None


def _get_data_path():
    """Caminho do arquivo JSON estático (ao lado do módulo)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ibge_municipios.json')


def _load_from_file():
    """Carrega mapa do arquivo JSON estático, se existir."""
    path = _get_data_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {str(m.get('id')): m.get('nome') for m in data if m.get('id') is not None and m.get('nome')}
        return None
    except Exception as e:
        logger.warning('Erro ao ler arquivo IBGE municípios: %s', e)
        return None


def _load_from_api():
    """Carrega mapa da API do IBGE."""
    try:
        import urllib.request
        import gzip
        import io
        url = 'https://servicodados.ibge.gov.br/api/v1/localidades/municipios'
        req = urllib.request.Request(url, headers={'User-Agent': 'RecordCRM/1.0', 'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        # Servidor pode devolver gzip mesmo com identity; descomprime se necessário
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb').read()
        data = json.loads(raw.decode('utf-8'))
        return {str(m.get('id')): m.get('nome') for m in data if m.get('id') is not None and m.get('nome')}
    except Exception as e:
        logger.warning('Não foi possível carregar nomes de municípios do IBGE (API): %s', e)
        return None


def _save_to_file(data):
    """Salva mapa no arquivo JSON para uso futuro."""
    path = _get_data_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info('IBGE municípios salvos em %s (%d)', path, len(data))
    except Exception as e:
        logger.warning('Não foi possível salvar arquivo IBGE municípios: %s', e)


def _load_ibge_municipios():
    global _IBGE_MAP, _IBGE_MAP_LOADED, _IBGE_MAP_6
    if _IBGE_MAP_LOADED:
        return
    _IBGE_MAP_LOADED = True
    # 1) Tenta arquivo estático primeiro (não depende de rede)
    _IBGE_MAP = _load_from_file()
    if _IBGE_MAP:
        logger.info('IBGE municípios carregados do arquivo: %d', len(_IBGE_MAP))
        # Índice 6 dígitos (2 UF + 4 mun) -> nome (primeiro 7-dig que bate)
        _IBGE_MAP_6 = {}
        for k, v in _IBGE_MAP.items():
            if len(k) == 7 and k.isdigit():
                key_6 = k[:2] + k[3:7]  # UF + dígitos 3-6 do código (4 dígitos municipais “no meio”)
                if key_6 not in _IBGE_MAP_6:
                    _IBGE_MAP_6[key_6] = v
        return
    # 2) Tenta API
    _IBGE_MAP = _load_from_api()
    if _IBGE_MAP:
        logger.info('IBGE municípios carregados da API: %d', len(_IBGE_MAP))
        _save_to_file(_IBGE_MAP)
        _IBGE_MAP_6 = {}
        for k, v in _IBGE_MAP.items():
            if len(k) == 7 and k.isdigit():
                key_6 = k[:2] + k[3:7]
                if key_6 not in _IBGE_MAP_6:
                    _IBGE_MAP_6[key_6] = v
        return
    _IBGE_MAP = {}
    _IBGE_MAP_6 = {}
    logger.warning('Nenhum dado de municípios IBGE disponível. Rode: python manage.py download_ibge_municipios')


# Mapeamento UF (sigla) -> código IBGE 2 dígitos (para montar código 7 dígitos a partir do código só do município)
_UF_PREFIX = {
    'ac': '12', 'al': '27', 'am': '13', 'ap': '16', 'ba': '29', 'ce': '23', 'df': '53', 'es': '32',
    'go': '52', 'ma': '21', 'mg': '31', 'ms': '50', 'mt': '51', 'pa': '15', 'pb': '25', 'pe': '26',
    'pi': '22', 'pr': '41', 'rj': '33', 'rn': '24', 'ro': '11', 'rr': '14', 'rs': '43', 'sc': '42',
    'se': '28', 'sp': '35', 'to': '17',
}


def get_nome_municipio_por_codigo(codigo_municipio, uf=None):
    """
    Retorna o nome do município para o código IBGE (7 dígitos) ou None.
    codigo_municipio pode ser str ou int; normaliza para 7 dígitos (IBGE).
    Se uf for informado e o código tiver 4 ou 5 dígitos (apenas município na UF),
    monta o código completo (2 dígitos UF + 5 dígitos município).
    Códigos de 6 dígitos são interpretados como 2 (UF) + 4 (município).
    """
    if codigo_municipio is None or codigo_municipio == '':
        return None
    _load_ibge_municipios()
    if not _IBGE_MAP:
        return None
    cod = str(codigo_municipio).strip()
    if not cod:
        return None
    # Apenas dígitos
    cod_digits = ''.join(c for c in cod if c.isdigit())
    if not cod_digits:
        return None
    # IBGE usa 7 dígitos (2 UF + 5 município)
    if len(cod_digits) > 7:
        cod_7 = cod_digits[-7:]
    elif len(cod_digits) == 6:
        # 6 dígitos: primeiros 2 = código UF IBGE, últimos 4 = município (completar com 1 zero)
        cod_7 = cod_digits[:2] + cod_digits[2:].zfill(5)
    elif len(cod_digits) in (4, 5) and uf:
        # Código só do município (4 ou 5 dígitos) + UF -> montar código completo
        uf_key = (uf or '').strip().lower()[:2]
        prefix = _UF_PREFIX.get(uf_key)
        if prefix:
            cod_7 = prefix + cod_digits.zfill(5)[-5:]
        else:
            cod_7 = cod_digits.zfill(7)
    else:
        cod_7 = cod_digits.zfill(7)
    # Tenta chave exata e também sem zeros à esquerda (API devolve id como número)
    nome = _IBGE_MAP.get(cod_7)
    if nome:
        return nome
    try:
        nome = _IBGE_MAP.get(str(int(cod_7)))
        if nome:
            return nome
    except ValueError:
        pass
    # Fallback: Receita às vezes envia só 4 dígitos. Tentar chave 6 dígitos (UF + 4 dígitos).
    if len(cod_digits) == 4 and uf and _IBGE_MAP_6 is not None:
        uf_key = (uf or '').strip().lower()[:2]
        prefix = _UF_PREFIX.get(uf_key)
        if prefix:
            key_6 = prefix + cod_digits
            nome = _IBGE_MAP_6.get(key_6)
            if nome:
                return nome
    return None
