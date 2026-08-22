# -*- coding: utf-8 -*-
"""
Classificação MEI / NMEI via BrasilAPI com cache Django.

Uso principal: consulta ao cadastrar venda com CNPJ (14 dígitos).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

BRASILAPI_CNPJ_URL = 'https://brasilapi.com.br/api/cnpj/v1/{cnpj}'
CACHE_KEY_PREFIX = 'cnpj_mei:v3:'
CACHE_KEY_RAZAO_PREFIX = 'cnpj_razao:v1:'
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 dias
REQUEST_TIMEOUT_SECONDS = 12

CLASSIFICACAO_MEI = 'MEI'
CLASSIFICACAO_NMEI = 'NMEI'
CLASSIFICACAO_INDETERMINADO = 'INDETERMINADO'
CLASSIFICACAO_CPF = 'CPF'

CLASSIFICACAO_CHOICES = [
    (CLASSIFICACAO_MEI, 'MEI'),
    (CLASSIFICACAO_NMEI, 'Não MEI'),
    (CLASSIFICACAO_INDETERMINADO, 'Indeterminado'),
    (CLASSIFICACAO_CPF, 'CPF (não aplicável)'),
]

CLASSIFICACAO_LABELS = {
    CLASSIFICACAO_MEI: 'MEI',
    CLASSIFICACAO_NMEI: 'NMEI',
    CLASSIFICACAO_INDETERMINADO: 'NMEI',
    CLASSIFICACAO_CPF: '-',
}


def classificacao_resumida_cnpj(codigo: Optional[str]) -> Optional[str]:
    """Somente MEI ou NMEI para persistência de CNPJ."""
    if codigo == CLASSIFICACAO_MEI:
        return CLASSIFICACAO_MEI
    if codigo:
        return CLASSIFICACAO_NMEI
    return None


def rotulo_classificacao_mei(codigo: Optional[str], *, documento: str = '') -> str:
    """Rótulo exibido: MEI, NMEI ou - (CPF / sem CNPJ)."""
    doc = _limpar_documento(documento)
    if len(doc) == 11:
        return '-'
    if codigo == CLASSIFICACAO_MEI:
        return CLASSIFICACAO_MEI
    if len(doc) == 14:
        return CLASSIFICACAO_NMEI if codigo else '-'
    return '-'


def classificacao_mei_venda(venda) -> Optional[str]:
    """MEI/NMEI efetivo: snapshot na venda ou cadastro do cliente."""
    cod = getattr(venda, 'classificacao_mei', None)
    if cod:
        return cod
    cliente = getattr(venda, 'cliente', None)
    if cliente:
        return getattr(cliente, 'classificacao_mei', None)
    return None


def tipo_cliente_comissao(
    venda=None,
    *,
    documento: str = '',
    classificacao_mei: Optional[str] = None,
) -> str:
    """
    Tipo para tabelas de comissão (REGRAS_FAIXAS / RegraComissao).
    CNPJ classificado como MEI usa colunas PAP (mesmo critério que CPF).
    """
    doc = _limpar_documento(documento)
    if not doc and venda is not None and getattr(venda, 'cliente', None):
        doc = _limpar_documento(venda.cliente.cpf_cnpj or '')
    if len(doc) != 14:
        return 'CPF'
    mei = classificacao_mei
    if mei is None and venda is not None:
        mei = classificacao_mei_venda(venda)
    if mei == CLASSIFICACAO_MEI:
        return 'CPF'
    return 'CNPJ'


def usa_tabela_cnpj_comissao(
    venda=None,
    *,
    documento: str = '',
    classificacao_mei: Optional[str] = None,
) -> bool:
    """True se deve usar colunas 500/700/1GB CNPJ (e não PAP)."""
    return tipo_cliente_comissao(
        venda, documento=documento, classificacao_mei=classificacao_mei
    ) == 'CNPJ'


def elegivel_desconto_boleto_folha(venda) -> bool:
    """
    Desconto de boleto na folha: CPF e CNPJ MEI (tabela PAP).
    CNPJ NMEI não entra. Adiantamento sábado quitado na instalação entra.
    Comissão antecipada na esteira (sem sábado quitado) não entra.
    """
    if venda is None:
        return False
    forma_pagamento = getattr(venda, 'forma_pagamento', None)
    if not forma_pagamento:
        return False
    if 'BOLETO' not in (getattr(forma_pagamento, 'nome', None) or '').upper():
        return False
    if usa_tabela_cnpj_comissao(venda):
        return False
    comissao_antecipada = bool(getattr(venda, 'antecipacao_comissao', False))
    sabado_quitado = bool(getattr(venda, 'adiantamento_sabado_quitado_em', None))
    if comissao_antecipada and not sabado_quitado:
        return False
    return True


def elegivel_adiantamento_cnpj(venda) -> bool:
    """Adiantamento CNPJ: somente CNPJ não MEI (NMEI ou sem classificação)."""
    if venda is None:
        return False
    cliente = getattr(venda, 'cliente', None)
    if not cliente:
        return False
    doc = _limpar_documento(cliente.cpf_cnpj or '')
    if len(doc) != 14:
        return False
    return classificacao_mei_venda(venda) != CLASSIFICACAO_MEI


def _normalizar_resultado_cnpj(resultado: ResultadoClassificacaoMei) -> ResultadoClassificacaoMei:
    if resultado.classificacao is None:
        return resultado
    resumido = classificacao_resumida_cnpj(resultado.classificacao) or CLASSIFICACAO_NMEI
    resultado.classificacao = resumido
    resultado.descricao = resumido
    return resultado


@dataclass
class ResultadoClassificacaoMei:
    classificacao: str
    descricao: str
    cnpj: str = ''
    codigo_natureza_juridica: Optional[int] = None
    natureza_juridica: str = ''
    opcao_pelo_mei: Optional[str] = None
    fonte: str = 'brasilapi'
    cache_hit: bool = False
    erro: Optional[str] = None

    def para_dict(self) -> dict[str, Any]:
        return {
            'classificacao_mei': self.classificacao,
            'classificacao_mei_descricao': self.descricao,
            'cnpj': self.cnpj,
            'codigo_natureza_juridica': self.codigo_natureza_juridica,
            'natureza_juridica': self.natureza_juridica,
            'opcao_pelo_mei': self.opcao_pelo_mei,
            'fonte': self.fonte,
            'cache_hit': self.cache_hit,
            'erro': self.erro,
        }


def _limpar_documento(doc: str) -> str:
    return re.sub(r'\D', '', str(doc or ''))


def _normalizar_nome_cadastro(nome: str) -> str:
    return re.sub(r'\s+', ' ', str(nome or '').strip().upper())


def extrair_razao_social_brasilapi(payload: Optional[dict]) -> str:
    """Razão social da Receita; fallback para nome fantasia."""
    if not payload:
        return ''
    razao = (payload.get('razao_social') or '').strip()
    if razao:
        return razao.upper()[:255]
    fantasia = (payload.get('nome_fantasia') or '').strip()
    if fantasia:
        return fantasia.upper()[:255]
    return ''


def _cache_key_razao(cnpj_limpo: str) -> str:
    return f'{CACHE_KEY_RAZAO_PREFIX}{cnpj_limpo}'


def resolver_razao_social_cnpj(cnpj: str, *, usar_cache: bool = True) -> tuple[str, Optional[str]]:
    """
    Consulta BrasilAPI e retorna (razao_social, erro).
    CPF ou documento inválido retorna ('', mensagem).
    """
    doc = _limpar_documento(cnpj)
    if len(doc) != 14:
        return '', 'CNPJ deve ter 14 dígitos.'

    chave = _cache_key_razao(doc)
    if usar_cache:
        cached = cache.get(chave)
        if isinstance(cached, str) and cached.strip():
            return cached, None

    payload = _consultar_brasilapi(doc, tentativas=2)
    if not payload:
        return '', 'Não foi possível consultar o CNPJ na Receita Federal.'
    razao = extrair_razao_social_brasilapi(payload)
    if not razao:
        return '', 'Razão social não encontrada na consulta.'
    if usar_cache:
        cache.set(chave, razao, CACHE_TTL_SECONDS)
    return razao, None


def consultar_dados_cnpj(cnpj: str, *, usar_cache: bool = True) -> dict[str, Any]:
    """Dados públicos do CNPJ para o formulário de venda (razão social, MEI/NMEI)."""
    doc = _limpar_documento(cnpj)
    if len(doc) != 14:
        return {'cnpj': doc, 'erro': 'CNPJ deve ter 14 dígitos.'}

    chave_razao = _cache_key_razao(doc)
    razao = ''
    fantasia = ''
    cache_hit = False
    payload: Optional[dict] = None

    if usar_cache:
        cached_razao = cache.get(chave_razao)
        if isinstance(cached_razao, str) and cached_razao.strip():
            razao = cached_razao
            cache_hit = True

    if not razao:
        payload = _consultar_brasilapi(doc, tentativas=2)
        if not payload:
            return {
                'cnpj': doc,
                'erro': 'Não foi possível consultar o CNPJ na Receita Federal.',
            }
        razao = extrair_razao_social_brasilapi(payload)
        if not razao:
            return {'cnpj': doc, 'erro': 'Razão social não encontrada na consulta.'}
        if usar_cache:
            cache.set(chave_razao, razao, CACHE_TTL_SECONDS)
        fantasia = (payload.get('nome_fantasia') or '').strip().upper()[:255]
        resultado_mei = _interpretar_resposta_brasilapi(payload, doc)
        resultado_mei = _normalizar_resultado_cnpj(resultado_mei)
        if usar_cache:
            cache.set(
                _cache_key(doc),
                {
                    'classificacao': resultado_mei.classificacao,
                    'descricao': resultado_mei.descricao,
                    'codigo_natureza_juridica': resultado_mei.codigo_natureza_juridica,
                    'natureza_juridica': resultado_mei.natureza_juridica,
                    'opcao_pelo_mei': resultado_mei.opcao_pelo_mei,
                    'fonte': resultado_mei.fonte,
                },
                CACHE_TTL_SECONDS,
            )
    else:
        resultado_mei = classificar_cnpj_mei(doc, usar_cache=usar_cache)
        cache_hit = cache_hit or resultado_mei.cache_hit

    return {
        'cnpj': doc,
        'razao_social': razao,
        'nome_fantasia': fantasia,
        'classificacao_mei': resultado_mei.classificacao,
        'classificacao_mei_descricao': resultado_mei.descricao,
        'cache_hit': cache_hit or resultado_mei.cache_hit,
    }


def _cache_key(cnpj_limpo: str) -> str:
    return f'{CACHE_KEY_PREFIX}{cnpj_limpo}'


def _mei_excluido(data_exclusao: Any) -> bool:
    """True se consta exclusão do MEI com data já vigente."""
    if not data_exclusao:
        return False
    from datetime import date

    try:
        dt = date.fromisoformat(str(data_exclusao).strip()[:10])
    except ValueError:
        return False
    return dt <= timezone.now().date()


def _porte_micro_empresa(payload: dict) -> bool:
    porte = (payload.get('porte') or '').upper()
    return 'MICRO' in porte


def _empresario_individual_micro(payload: dict, codigo_nj_int: Optional[int]) -> bool:
    """Cartão CNPJ típico de MEI: 213-5 Empresário (Individual) + porte micro."""
    return codigo_nj_int == 2135 and _porte_micro_empresa(payload)


def _saida_definitiva_mei(payload: dict, codigo_nj_int: Optional[int]) -> bool:
    """
    Exclusão que deve classificar como NMEI.

    Para 213-5 + micro, a BrasilAPI costuma trazer data_exclusao_do_mei em 31/12
    (fim de exercício), com opcao_pelo_mei=False mesmo com MEI ativo no cartão.
    """
    excl = payload.get('data_exclusao_do_mei')
    if not _mei_excluido(excl):
        return False

    if _empresario_individual_micro(payload, codigo_nj_int):
        from datetime import date

        try:
            dt_excl = date.fromisoformat(str(excl).strip()[:10])
        except ValueError:
            return False
        # Fim de ano civil no cadastro — não tratar como desenquadramento.
        if dt_excl.month == 12 and dt_excl.day == 31:
            return False
        return False

    return True


def _opcao_mei_ativa_no_payload(payload: dict) -> bool:
    """
    BrasilAPI envia opcao_pelo_mei como bool ou string.
    False não significa 'não é MEI' — só True indica optante explícito.
    """
    valor = payload.get('opcao_pelo_mei')
    if valor is True:
        return True
    if isinstance(valor, str):
        return valor.strip().upper() in ('S', 'SIM', 'TRUE', '1')
    return False


def _interpretar_resposta_brasilapi(payload: dict, cnpj_limpo: str) -> ResultadoClassificacaoMei:
    codigo_nj = payload.get('codigo_natureza_juridica')
    try:
        codigo_nj_int = int(codigo_nj) if codigo_nj is not None else None
    except (TypeError, ValueError):
        codigo_nj_int = None

    natureza = (payload.get('natureza_juridica') or '').strip()
    excluido = payload.get('data_exclusao_do_mei')
    opcao_raw = payload.get('opcao_pelo_mei')

    if _opcao_mei_ativa_no_payload(payload):
        classificacao = CLASSIFICACAO_MEI
    elif _saida_definitiva_mei(payload, codigo_nj_int):
        classificacao = CLASSIFICACAO_NMEI
    elif _empresario_individual_micro(payload, codigo_nj_int):
        classificacao = CLASSIFICACAO_MEI
    elif codigo_nj_int == 2135:
        classificacao = CLASSIFICACAO_MEI
    else:
        classificacao = CLASSIFICACAO_NMEI

    opcao_label = None
    if isinstance(opcao_raw, bool):
        opcao_label = 'S' if opcao_raw else None
    elif opcao_raw is not None:
        opcao_label = str(opcao_raw).strip().upper() or None

    return _normalizar_resultado_cnpj(ResultadoClassificacaoMei(
        classificacao=classificacao,
        descricao=classificacao,
        cnpj=cnpj_limpo,
        codigo_natureza_juridica=codigo_nj_int,
        natureza_juridica=natureza,
        opcao_pelo_mei=opcao_label,
        fonte='brasilapi',
    ))


def _consultar_brasilapi(cnpj_limpo: str, *, tentativas: int = 1) -> Optional[dict]:
    import urllib.error
    import urllib.request

    url = BRASILAPI_CNPJ_URL.format(cnpj=cnpj_limpo)
    req = urllib.request.Request(url, headers={'User-Agent': 'RecordCRM/1.0'})
    max_tentativas = max(1, int(tentativas))
    for tentativa in range(1, max_tentativas + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429 and tentativa < max_tentativas:
                import time as _time
                _time.sleep(2 * tentativa)
                continue
            logger.warning('[CNPJ MEI] BrasilAPI HTTP %s para %s', e.code, cnpj_limpo)
            return None
        except Exception as e:
            if tentativa < max_tentativas:
                logger.warning(
                    '[CNPJ MEI] Tentativa %s/%s falhou para %s: %s',
                    tentativa, max_tentativas, cnpj_limpo, e,
                )
                continue
            logger.warning('[CNPJ MEI] Erro BrasilAPI para %s: %s', cnpj_limpo, e)
            return None
    return None


def classificar_cnpj_mei(cnpj: str, *, usar_cache: bool = True) -> ResultadoClassificacaoMei:
    """
    Classifica CNPJ como MEI ou NMEI. CPF (11 dígitos) não recebe classificação.
    """
    doc = _limpar_documento(cnpj)
    if len(doc) == 11:
        return ResultadoClassificacaoMei(
            classificacao=None,
            descricao='-',
            fonte='local',
        )
    if len(doc) != 14:
        return ResultadoClassificacaoMei(
            classificacao=CLASSIFICACAO_NMEI,
            descricao=CLASSIFICACAO_NMEI,
            cnpj=doc,
            fonte='local',
            erro='CNPJ deve ter 14 dígitos.',
        )

    chave = _cache_key(doc)
    if usar_cache:
        cached = cache.get(chave)
        if isinstance(cached, dict) and cached.get('classificacao'):
            cod_cache = classificacao_resumida_cnpj(cached['classificacao'])
            return ResultadoClassificacaoMei(
                classificacao=cod_cache or CLASSIFICACAO_NMEI,
                descricao=cod_cache or CLASSIFICACAO_NMEI,
                cnpj=doc,
                codigo_natureza_juridica=cached.get('codigo_natureza_juridica'),
                natureza_juridica=cached.get('natureza_juridica') or '',
                opcao_pelo_mei=cached.get('opcao_pelo_mei'),
                fonte=cached.get('fonte') or 'cache',
                cache_hit=True,
            )

    payload = _consultar_brasilapi(doc, tentativas=2)
    if not payload:
        resultado = ResultadoClassificacaoMei(
            classificacao=CLASSIFICACAO_NMEI,
            descricao=CLASSIFICACAO_NMEI,
            cnpj=doc,
            fonte='brasilapi',
            erro='Não foi possível consultar o CNPJ na BrasilAPI.',
        )
    else:
        resultado = _interpretar_resposta_brasilapi(payload, doc)

    resultado = _normalizar_resultado_cnpj(resultado)

    if usar_cache:
        cache.set(
            chave,
            {
                'classificacao': resultado.classificacao,
                'descricao': resultado.descricao,
                'codigo_natureza_juridica': resultado.codigo_natureza_juridica,
                'natureza_juridica': resultado.natureza_juridica,
                'opcao_pelo_mei': resultado.opcao_pelo_mei,
                'fonte': resultado.fonte,
            },
            CACHE_TTL_SECONDS,
        )
    return resultado


def _aplicar_resultado_no_cliente(cliente, resultado: ResultadoClassificacaoMei) -> None:
    doc = _limpar_documento(cliente.cpf_cnpj)
    if len(doc) == 11:
        cliente.classificacao_mei = None
    else:
        cliente.classificacao_mei = resultado.classificacao
    cliente.classificacao_mei_consultada_em = timezone.now()
    cliente.save(update_fields=['classificacao_mei', 'classificacao_mei_consultada_em'])


def persistir_classificacao_mei(cliente, venda=None, *, usar_cache: bool = True) -> ResultadoClassificacaoMei:
    """
    Consulta (se CNPJ), grava em Cliente e opcionalmente na Venda.
    """
    from crm_app.models import Cliente, Venda

    if not isinstance(cliente, Cliente):
        raise TypeError('cliente deve ser instância de Cliente')

    resultado = classificar_cnpj_mei(cliente.cpf_cnpj, usar_cache=usar_cache)
    _aplicar_resultado_no_cliente(cliente, resultado)

    if venda is not None and isinstance(venda, Venda):
        doc = _limpar_documento(cliente.cpf_cnpj)
        venda.classificacao_mei = None if len(doc) == 11 else resultado.classificacao
        venda.save(update_fields=['classificacao_mei'])

    return resultado


def persistir_classificacao_mei_cliente_e_vendas(cliente, *, usar_cache: bool = True) -> ResultadoClassificacaoMei:
    """Atualiza cliente e todas as vendas vinculadas (backfill histórico)."""
    from crm_app.models import Cliente, Venda

    if not isinstance(cliente, Cliente):
        raise TypeError('cliente deve ser instância de Cliente')

    resultado = classificar_cnpj_mei(cliente.cpf_cnpj, usar_cache=usar_cache)
    _aplicar_resultado_no_cliente(cliente, resultado)
    doc = _limpar_documento(cliente.cpf_cnpj)
    if len(doc) == 11:
        Venda.objects.filter(cliente_id=cliente.id).update(classificacao_mei=None)
    else:
        Venda.objects.filter(cliente_id=cliente.id).update(classificacao_mei=resultado.classificacao)
    return resultado


def normalizar_classificacoes_legadas_no_banco() -> dict[str, int]:
    """Converte INDETERMINADO/CPF em MEI/NMEI (ou limpa CPF pessoa física)."""
    from django.db.models import Q
    from django.db.models.functions import Length

    from crm_app.models import Cliente, Venda

    upd_cli = Cliente.objects.filter(classificacao_mei='INDETERMINADO').update(
        classificacao_mei=CLASSIFICACAO_NMEI
    )
    upd_ven = Venda.objects.filter(classificacao_mei='INDETERMINADO').update(
        classificacao_mei=CLASSIFICACAO_NMEI
    )
    cli_cpf = Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(doc_len=11)
    ven_cpf = Venda.objects.filter(
        cliente_id__in=cli_cpf.values_list('id', flat=True)
    )
    limp_cli = cli_cpf.exclude(
        Q(classificacao_mei__isnull=True) | Q(classificacao_mei='')
    ).update(classificacao_mei=None)
    limp_ven = ven_cpf.exclude(
        Q(classificacao_mei__isnull=True) | Q(classificacao_mei='')
    ).update(classificacao_mei=None)
    corr_cli = Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(
        doc_len=14, classificacao_mei='CPF'
    ).update(classificacao_mei=CLASSIFICACAO_NMEI)
    corr_ven = Venda.objects.filter(classificacao_mei='CPF').update(
        classificacao_mei=CLASSIFICACAO_NMEI
    )
    return {
        'clientes_indeterminado_para_nmei': upd_cli,
        'vendas_indeterminado_para_nmei': upd_ven,
        'clientes_cpf_limpos': limp_cli,
        'vendas_cpf_limpos': limp_ven,
        'clientes_cpf_errado_cnpj': corr_cli,
        'vendas_cpf_errado': corr_ven,
    }


def queryset_clientes_cnpj_todos():
    """Todos os clientes com CNPJ (14 dígitos no cadastro)."""
    from django.db.models.functions import Length

    from crm_app.models import Cliente

    return Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(doc_len=14).order_by('id')


def backfill_razao_social_cnpj_lote(
    *,
    offset: int = 0,
    limite: int = 20,
    forcar_todos: bool = False,
    pausa_api_segundos: float = 0.5,
) -> dict[str, Any]:
    """
    Corrige nome_razao_social dos clientes CNPJ conforme a Receita Federal (BrasilAPI).
    Com forcar_todos: pagina todos os CNPJs; senão só os com nome diferente da API.
    """
    import time

    limite = max(1, min(int(limite), 50))
    offset = max(0, int(offset))

    qs = queryset_clientes_cnpj_todos()
    total_cnpj = qs.count()

    if forcar_todos:
        candidatos = list(qs[offset: offset + limite])
    else:
        candidatos = []
        for cliente in qs.iterator(chunk_size=200):
            razao_api, erro = resolver_razao_social_cnpj(cliente.cpf_cnpj, usar_cache=True)
            if erro or not razao_api:
                continue
            if _normalizar_nome_cadastro(cliente.nome_razao_social) != _normalizar_nome_cadastro(razao_api):
                candidatos.append(cliente)
            if len(candidatos) >= limite:
                break

    atualizados = 0
    iguais = 0
    sem_razao = 0
    erros = 0

    for cliente in candidatos:
        try:
            razao_api, erro = resolver_razao_social_cnpj(
                cliente.cpf_cnpj,
                usar_cache=not forcar_todos,
            )
            if erro or not razao_api:
                if erro:
                    erros += 1
                else:
                    sem_razao += 1
                continue
            if _normalizar_nome_cadastro(cliente.nome_razao_social) == _normalizar_nome_cadastro(razao_api):
                iguais += 1
                continue
            cliente.nome_razao_social = razao_api
            cliente.save(update_fields=['nome_razao_social'])
            atualizados += 1
            if pausa_api_segundos > 0:
                time.sleep(pausa_api_segundos)
        except Exception:
            logger.exception('[CNPJ] Erro ao corrigir razão social cliente id=%s', cliente.id)
            erros += 1

    processados = len(candidatos)
    proximo_offset = offset + processados

    if forcar_todos:
        restantes = max(0, total_cnpj - proximo_offset)
        concluido = processados == 0 or proximo_offset >= total_cnpj
    else:
        restantes = None
        for cliente in qs.iterator(chunk_size=200):
            razao_api, erro = resolver_razao_social_cnpj(cliente.cpf_cnpj, usar_cache=True)
            if erro or not razao_api:
                continue
            if _normalizar_nome_cadastro(cliente.nome_razao_social) != _normalizar_nome_cadastro(razao_api):
                restantes = (restantes or 0) + 1
        restantes = restantes or 0
        concluido = processados == 0 or restantes == 0

    return {
        'total_cnpj': total_cnpj,
        'restantes': restantes,
        'processados_lote': processados,
        'proximo_offset': proximo_offset,
        'concluido': concluido,
        'atualizados': atualizados,
        'iguais': iguais,
        'sem_razao_api': sem_razao,
        'erros': erros,
    }


def queryset_clientes_cnpj(*, apenas_sem_classificacao: bool = True, forcar_todos: bool = False):
    """Clientes com CNPJ (14 dígitos no cadastro), opcionalmente sem classificação."""
    from django.db.models import Q
    from django.db.models.functions import Length

    from crm_app.models import Cliente

    qs = Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(doc_len=14)
    if not forcar_todos and apenas_sem_classificacao:
        qs = qs.filter(Q(classificacao_mei__isnull=True) | Q(classificacao_mei=''))
    return qs.order_by('id')


def backfill_classificacao_mei_lote(
    *,
    offset: int = 0,
    limite: int = 20,
    apenas_sem_classificacao: bool = True,
    forcar_todos: bool = False,
    pausa_api_segundos: float = 0.5,
) -> dict[str, Any]:
    """
    Processa um lote de CNPJs para preencher classificacao_mei em Cliente e Vendas.

    Sem ``forcar_todos``: sempre os primeiros ``limite`` ainda sem classificação (fila encolhe).
    Com ``forcar_todos``: paginação por offset em todos os CNPJs (fila fixa em 380).
    """
    import time

    limite = max(1, min(int(limite), 50))
    offset = max(0, int(offset))

    qs = queryset_clientes_cnpj(
        apenas_sem_classificacao=apenas_sem_classificacao,
        forcar_todos=forcar_todos,
    )
    total_pendentes = qs.count()

    if forcar_todos:
        clientes = list(qs[offset: offset + limite])
    else:
        clientes = list(qs[:limite])

    contagem = {
        CLASSIFICACAO_MEI: 0,
        CLASSIFICACAO_NMEI: 0,
    }
    vendas_atualizadas = 0
    erros = 0

    from crm_app.models import Venda

    for cliente in clientes:
        try:
            qtd_vendas = Venda.objects.filter(cliente_id=cliente.id).count()
            resultado = persistir_classificacao_mei_cliente_e_vendas(
                cliente, usar_cache=not forcar_todos
            )
            contagem[resultado.classificacao] = contagem.get(resultado.classificacao, 0) + 1
            vendas_atualizadas += qtd_vendas
            if not resultado.cache_hit and pausa_api_segundos > 0:
                time.sleep(pausa_api_segundos)
        except Exception:
            logger.exception('[CNPJ MEI] Erro no backfill cliente id=%s', cliente.id)
            erros += 1

    processados = len(clientes)
    proximo_offset = offset + processados

    if forcar_todos:
        restantes = max(0, total_pendentes - proximo_offset)
        concluido = processados == 0 or proximo_offset >= total_pendentes
    else:
        restantes = queryset_clientes_cnpj(
            apenas_sem_classificacao=apenas_sem_classificacao,
            forcar_todos=False,
        ).count()
        concluido = processados == 0 or restantes == 0

    return {
        'total_pendentes': total_pendentes,
        'restantes': restantes,
        'processados_lote': processados,
        'proximo_offset': proximo_offset,
        'processados_acumulado': proximo_offset if forcar_todos else None,
        'concluido': concluido,
        'mei': contagem.get(CLASSIFICACAO_MEI, 0),
        'nmei': contagem.get(CLASSIFICACAO_NMEI, 0),
        'indeterminado': 0,
        'erros': erros,
        'vendas_atualizadas': vendas_atualizadas,
    }
