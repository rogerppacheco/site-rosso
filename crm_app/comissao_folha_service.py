# crm_app/comissao_folha_service.py
"""
Serviço de cálculo da folha de comissão no formato Excel (REGRAS_FAIXAS + REGRAS_VENDEDORES).
Mapeamento: plano.nome + tipo_cliente (+ cidade especial) -> chave de exibição na folha.
"""
from decimal import Decimal
from collections import defaultdict
from datetime import datetime

# Chaves de exibição/agregação na Gestão de Comissionamento (ordem da tabela).
CHAVES_PLANO = [
    '500MB_PAP',
    '600MB_PAP',
    '600MB_ESP_PAP',
    '700MB_PAP',
    '1GB_PAP',
    '500MB_CNPJ',
    '600MB_CNPJ',
    '600MB_ESP_CNPJ',
    '700MB_CNPJ',
    '1GB_CNPJ',
]

LABELS_CHAVE_PLANO = {
    '500MB_PAP': '500MB PAP',
    '600MB_PAP': '600MB PAP',
    '600MB_ESP_PAP': '600MB Cidade Especial PAP',
    '700MB_PAP': '700MB PAP',
    '1GB_PAP': '1GB PAP',
    '500MB_CNPJ': '500MB CNPJ',
    '600MB_CNPJ': '600MB CNPJ',
    '600MB_ESP_CNPJ': '600MB Cidade Especial CNPJ',
    '700MB_CNPJ': '700MB CNPJ',
    '1GB_CNPJ': '1GB CNPJ',
}

# Mapa chave de exibição -> coluna legada (matriz/manual 500/700/1GB).
_CHAVE_PARA_LEGADO = {
    '600MB_PAP': '500MB_PAP',
    '600MB_ESP_PAP': '500MB_PAP',
    '600MB_CNPJ': '500MB_CNPJ',
    '600MB_ESP_CNPJ': '500MB_CNPJ',
    # 800MB continua agregado em 700MB (sem linha própria neste momento).
}


# Nomes de plano (normalizado) -> banda para chave
def _plano_nome_to_banda(nome):
    if not nome:
        return None
    n = (nome or '').upper().replace(' ', '')
    if '500' in n:
        return '500MB'
    if '600' in n:
        return '600MB'
    if '700' in n:
        return '700MB'
    if '800' in n:
        return '800MB'
    if '1GB' in n or '1G' in n:
        return '1GB'
    return None


def _banda_legado_comissao(banda: str | None) -> str | None:
    """
    Normaliza banda para colunas legadas das faixas (500/700/1GB).
    600MB e 800MB são planos de transição: herdam a tabela do degrau anterior.
    """
    if not banda:
        return None
    if banda == '600MB':
        return '500MB'
    if banda == '800MB':
        return '700MB'
    return banda


def chave_legado_lookup(chave: str | None) -> str | None:
    """Converte chave de exibição (ex.: 600MB_ESP_PAP) para coluna legada da matriz."""
    if not chave:
        return None
    return _CHAVE_PARA_LEGADO.get(chave, chave)


def plano_tipo_to_chave(
    plano_nome,
    tipo_cliente,
    *,
    venda=None,
    cidades_especiais_cache=None,
):
    """
    Retorna a chave de exibição na folha (ex.: 600MB_ESP_PAP, 500MB_PAP).

    - 600MB em cidade de oferta especial → 600MB_ESP_*
    - 600MB demais cidades → 600MB_*
    - 800MB ainda agrega em 700MB_* (legado)
    - Demais bandas → chave própria
    """
    banda_real = _plano_nome_to_banda(plano_nome)
    if not banda_real:
        return None
    sufixo = 'PAP' if tipo_cliente == 'CPF' else 'CNPJ'

    if banda_real == '600MB':
        from crm_app.services.comissao_cidade_especial_service import (
            venda_em_cidade_oferta_especial,
        )
        if venda is not None and venda_em_cidade_oferta_especial(
            venda, cache=cidades_especiais_cache,
        ):
            chave = f'600MB_ESP_{sufixo}'
        else:
            chave = f'600MB_{sufixo}'
        return chave if chave in CHAVES_PLANO else None

    banda = _banda_legado_comissao(banda_real)
    if not banda:
        return None
    chave = f'{banda}_{sufixo}'
    return chave if chave in CHAVES_PLANO else None


def estimar_comissao_instaladas_vendedor(
    vendedor,
    vendas_instaladas,
    *,
    ctx_faixas: dict,
    matriz_cache=None,
) -> float:
    """
    Estimativa de comissão do dashboard CRM, baseada nas instalações.

    Usa a mesma fonte da folha (faixa × plano / valores manuais), e não a
    tabela legado RegraComissao — que omitia planos novos e canais fora de PAP/TELAG.
    """
    from crm_app.performance_helpers import (
        _regras_aplicaveis_vendedor,
        encontrar_faixa_regra,
        perfil_comissao_do_consultor,
    )
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao
    from crm_app.services.comissao_cidade_especial_service import carregar_cidades_oferta_especial
    from crm_app.services.plano_comissao_service import get_valor_comissao_plano

    vendas = list(vendas_instaladas)
    config = (ctx_faixas.get('configs') or {}).get(getattr(vendedor, 'id', None))
    perfil = perfil_comissao_do_consultor(vendedor, config)
    regras = _regras_aplicaveis_vendedor(ctx_faixas, getattr(vendedor, 'id', None), perfil)
    faixa_regra = encontrar_faixa_regra(regras, len(vendas))
    usar_manual = bool(config and getattr(config, 'usar_valor_manual', False))
    cidades_cache = carregar_cidades_oferta_especial()

    total = 0.0
    for venda in vendas:
        plano = getattr(venda, 'plano', None)
        if not plano:
            continue
        tipo_cliente = tipo_cliente_comissao(venda)
        chave = plano_tipo_to_chave(
            getattr(plano, 'nome', None),
            tipo_cliente,
            venda=venda,
            cidades_especiais_cache=cidades_cache,
        )
        valor = resolver_valor_comissao_venda(
            plano,
            tipo_cliente,
            faixa_regra=faixa_regra,
            config=config,
            usar_manual=usar_manual,
            chave=chave,
            matriz_cache=matriz_cache,
            venda=venda,
            cidades_especiais_cache=cidades_cache,
        )
        if valor is None:
            valor = get_valor_comissao_plano(plano, tipo_cliente)
        total += float(valor or 0)
    return total


def get_valor_from_faixa(regra_faixa, chave):
    """Retorna o valor decimal da regra de faixa para a chave (500MB_PAP, etc.)."""
    if not regra_faixa or not chave:
        return None
    chave_lookup = chave_legado_lookup(chave)
    m = {
        '500MB_PAP': regra_faixa.valor_500mb_pap,
        '700MB_PAP': regra_faixa.valor_700mb_pap,
        '1GB_PAP': regra_faixa.valor_1gb_pap,
        '500MB_CNPJ': regra_faixa.valor_500mb_cnpj,
        '700MB_CNPJ': regra_faixa.valor_700mb_cnpj,
        '1GB_CNPJ': regra_faixa.valor_1gb_cnpj,
    }
    v = m.get(chave_lookup)
    return float(v) if v is not None else None


def _normalizar_perfil_comissao_folha(valor: str | None) -> str | None:
    v = (valor or '').strip().upper()
    if not v:
        return None
    if v == 'SUPERVISOR':
        return 'Supervisor'
    if v == 'VENDEDOR':
        return 'Vendedor'
    return None


def resolver_perfil_comissao_consultor(consultor, config=None) -> str:
    """Perfil de comissão do consultor (usuário → config → padrão Vendedor)."""
    perfil_usuario = getattr(getattr(consultor, 'perfil', None), 'nome', None)
    perfil_resolvido = _normalizar_perfil_comissao_folha(perfil_usuario)
    if perfil_resolvido:
        return perfil_resolvido
    perfil_config = _normalizar_perfil_comissao_folha(getattr(config, 'perfil_comissao', None))
    if perfil_config:
        return perfil_config
    return 'Vendedor'


def carregar_faixa_adiantamento_regras_faixa(consultor=None, config=None, perfil: str | None = None):
    """
    Faixa de referência para adiantamento na esteira / exibição na folha.
    Usa o perfil do vendedor (Vendedor ou Supervisor), nunca a primeira faixa global.
    Prioridade: finalidade ADIANTAMENTO do perfil → menor faixa COMISSAO do perfil.
    """
    from .models import RegraComissaoFaixa

    if perfil is None and consultor is not None:
        perfil = resolver_perfil_comissao_consultor(consultor, config)

    if perfil:
        faixa_adiant = (
            RegraComissaoFaixa.objects.filter(
                finalidade='ADIANTAMENTO',
                perfil=perfil,
                vendedor__isnull=True,
            )
            .order_by('min_vendas', 'id')
            .first()
        )
        if faixa_adiant:
            return faixa_adiant
        faixa_comissao = (
            RegraComissaoFaixa.objects.filter(
                finalidade='COMISSAO',
                perfil=perfil,
                vendedor__isnull=True,
            )
            .order_by('min_vendas', 'id')
            .first()
        )
        if faixa_comissao:
            return faixa_comissao

    return RegraComissaoFaixa.objects.filter(finalidade='COMISSAO').order_by('id').first()


def carregar_valores_adiantamento_esteira_lancamentos(vendedor_id: int | None = None) -> dict[int, float]:
    """Mapa venda_id → valor pago no adiantamento da esteira (instaladas / agendados)."""
    from .models import LancamentoFinanceiro

    origens_esteira = {'instaladas_comissao', 'esteira_sabado_agendados'}
    qs = LancamentoFinanceiro.objects.filter(tipo='ADIANTAMENTO_COMISSAO')
    if vendedor_id:
        qs = qs.filter(usuario_id=vendedor_id)

    mapa: dict[int, float] = {}
    for lanc in qs.only('valor', 'metadados', 'quantidade_vendas'):
        meta = lanc.metadados if isinstance(lanc.metadados, dict) else {}
        if meta.get('origem') not in origens_esteira:
            continue
        valores_por_venda = meta.get('valores_por_venda_id') or {}
        for vid, val in valores_por_venda.items():
            try:
                mapa[int(vid)] = float(val)
            except (TypeError, ValueError):
                continue
    return mapa


def valor_comissao_tabela_adiantamento(
    venda,
    faixa_adiantamento,
    chave,
    matriz_cache=None,
    cidades_especiais_cache=None,
):
    """Valor por venda: cidade especial → matriz faixa×plano → colunas legadas → comissao_base."""
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao
    from crm_app.services.comissao_cidade_especial_service import resolver_valor_cidade_especial
    from crm_app.services.comissao_matriz_service import get_valor_faixa_plano

    tipo = tipo_cliente_comissao(venda)
    valor_especial = resolver_valor_cidade_especial(
        venda.plano if venda else None,
        tipo,
        venda=venda,
        cache=cidades_especiais_cache,
    )
    if valor_especial is not None:
        return valor_especial
    if venda.plano and faixa_adiantamento:
        v_matriz = get_valor_faixa_plano(
            faixa_adiantamento, venda.plano, tipo, matriz_cache=matriz_cache,
        )
        if v_matriz is not None:
            return v_matriz
    if faixa_adiantamento and chave:
        v = get_valor_from_faixa(faixa_adiantamento, chave)
        if v is not None:
            return float(v)
    if venda.plano and venda.plano.comissao_base is not None:
        return float(venda.plano.comissao_base)
    return 0.0


def valor_adiantamento_exibicao_folha(
    venda,
    faixa_adiantamento,
    chave,
    origem=None,
    complemento_sabado: float | None = None,
    valores_esteira_lancamento: dict[int, float] | None = None,
    matriz_cache=None,
    cidades_especiais_cache=None,
):
    """
    Valor de comissão antecipada na folha/extrato.
    Adiantamento sábado: valor pago no sábado + complemento de faixa (se instalada).
    Adiantamento comissão (esteira): valor do lançamento ou faixa do perfil do vendedor.
    """
    if origem is None:
        origem = origem_adiantamento_comissao_venda(venda)
    if origem in ('sabado', 'sabado_quitado_instalacao', 'sabado_pendente'):
        from crm_app.services.adiantamento_sabado_service import (
            valor_pago_adiantamento_sabado_venda,
        )

        pago = valor_pago_adiantamento_sabado_venda(venda)
        if pago > 0:
            comp = float(complemento_sabado or 0)
            if comp != 0 and origem in ('sabado', 'sabado_quitado_instalacao'):
                return round(pago + comp, 2)
            if origem == 'sabado_pendente' or comp == 0:
                return pago
            return round(pago + comp, 2)
    if origem == 'esteira_comissao':
        vid = getattr(venda, 'pk', None) or getattr(venda, 'id', None)
        if valores_esteira_lancamento and vid is not None:
            val_lanc = valores_esteira_lancamento.get(int(vid))
            if val_lanc is not None and float(val_lanc) > 0:
                return float(val_lanc)
    return valor_comissao_tabela_adiantamento(
        venda,
        faixa_adiantamento,
        chave,
        matriz_cache=matriz_cache,
        cidades_especiais_cache=cidades_especiais_cache,
    )


def data_instalacao_efetiva_folha(venda):
    """
    Data de instalação usada na folha (OSAB + física no cliente):
    - OSAB e física preenchidas → data física (no cliente)
    - Só OSAB → OSAB
    - Só física → física
    """
    osab = getattr(venda, 'data_instalacao', None)
    fis = getattr(venda, 'data_instalacao_fisica', None)
    if osab and fis:
        return fis
    if osab:
        return osab
    return fis


def annotate_data_folha_comissao(queryset):
    """
    Anota data_folha_comissao com a mesma regra de data_instalacao_efetiva_folha (SQL).
    """
    from django.db.models import Case, When, F, Q, DateField

    data_folha = Case(
        When(
            Q(data_instalacao__isnull=False) & Q(data_instalacao_fisica__isnull=False),
            then=F('data_instalacao_fisica'),
        ),
        When(data_instalacao__isnull=False, then=F('data_instalacao')),
        default=F('data_instalacao_fisica'),
        output_field=DateField(),
    )
    return queryset.annotate(data_folha_comissao=data_folha)


def vendas_instaladas_folha_periodo(consultor, data_inicio, data_fim):
    """Vendas INSTALADAS cujo mês de referência na folha cai em [data_inicio, data_fim)."""
    from .models import Venda

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    base = Venda.objects.filter(
        vendedor=consultor,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
    )
    return (
        annotate_data_folha_comissao(base)
        .filter(
            data_folha_comissao__isnull=False,
            data_folha_comissao__gte=di,
            data_folha_comissao__lt=df,
        )
        .select_related(
            'plano', 'plano__valores_comissao', 'cliente',
            'forma_pagamento', 'status_tratamento', 'status_esteira',
        )
        .order_by('data_folha_comissao', 'id')
    )


def _agrupar_vendas_folha_bulk(vendedor_ids, data_inicio, data_fim):
    """Carrega vendas da folha de todos os vendedores em uma única query."""
    from collections import defaultdict
    from .models import Venda

    if not vendedor_ids:
        return {}
    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    qs = (
        annotate_data_folha_comissao(
            Venda.objects.filter(
                vendedor_id__in=vendedor_ids,
                ativo=True,
                status_esteira__nome__iexact='INSTALADA',
            )
        )
        .filter(
            data_folha_comissao__isnull=False,
            data_folha_comissao__gte=di,
            data_folha_comissao__lt=df,
        )
        .select_related(
            'plano', 'plano__valores_comissao', 'cliente',
            'forma_pagamento', 'status_tratamento', 'status_esteira',
        )
        .order_by('vendedor_id', 'data_folha_comissao', 'id')
    )
    grupos = defaultdict(list)
    for venda in qs:
        grupos[venda.vendedor_id].append(venda)
    return dict(grupos)


def _agrupar_lancamentos_bulk(usuario_ids, data_inicio, data_fim):
    """Carrega lançamentos financeiros do período em uma única query."""
    from collections import defaultdict
    from .models import LancamentoFinanceiro

    if not usuario_ids:
        return {}
    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    qs = (
        LancamentoFinanceiro.objects.filter(
            usuario_id__in=usuario_ids,
            data__gte=di,
            data__lt=df,
        )
        .order_by('usuario_id', 'data', 'id')
    )
    grupos = defaultdict(list)
    for lanc in qs:
        grupos[lanc.usuario_id].append(lanc)
    return dict(grupos)


def resolver_valor_comissao_venda(
    plano,
    tipo_cliente: str,
    *,
    faixa_regra,
    config,
    usar_manual: bool,
    chave: str | None,
    matriz_cache=None,
    venda=None,
    cidades_especiais_cache=None,
) -> float | None:
    """Valor de comissão: cidade especial → manual por plano → matriz faixa×plano → legado."""
    from crm_app.services.comissao_cidade_especial_service import resolver_valor_cidade_especial
    from crm_app.services.comissao_matriz_service import get_valor_faixa_plano

    valor_especial = resolver_valor_cidade_especial(
        plano,
        tipo_cliente,
        venda=venda,
        cache=cidades_especiais_cache,
    )
    if valor_especial is not None:
        return valor_especial

    if usar_manual:
        return get_valor_manual(config, chave, plano, matriz_cache=matriz_cache)
    if faixa_regra and plano:
        v = get_valor_faixa_plano(faixa_regra, plano, tipo_cliente, matriz_cache=matriz_cache)
        if v is not None:
            return v
    if faixa_regra and chave:
        return get_valor_from_faixa(faixa_regra, chave)
    return None


def get_valor_manual(config, chave, plano=None, matriz_cache=None):
    """Retorna valor manual do vendedor (por plano ou colunas legadas 500/700/1GB)."""
    if plano and config and chave:
        from crm_app.services.comissao_matriz_service import get_valor_manual_vendedor_plano
        tipo = 'CPF' if str(chave).endswith('_PAP') else 'CNPJ'
        v_plano = get_valor_manual_vendedor_plano(config, plano, tipo, matriz_cache=matriz_cache)
        if v_plano is not None:
            return v_plano
    if not config or not chave:
        return None
    chave_lookup = chave_legado_lookup(chave)
    m = {
        '500MB_PAP': config.valor_500mb_pap_manual,
        '700MB_PAP': config.valor_700mb_pap_manual,
        '1GB_PAP': config.valor_1gb_pap_manual,
        '500MB_CNPJ': config.valor_500mb_cnpj_manual,
        '700MB_CNPJ': config.valor_700mb_cnpj_manual,
        '1GB_CNPJ': config.valor_1gb_cnpj_manual,
    }
    v = m.get(chave_lookup)
    return float(v) if v is not None else None


def origem_adiantamento_comissao_venda(venda) -> str | None:
    """
    Classifica a origem do adiantamento quando a venda foi antecipada.
    None se não houver antecipação de comissão na folha.
    """
    from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

    sab_marcado = bool(getattr(venda, 'adiantamento_sabado_marcado', False))
    sab_quitado = bool(getattr(venda, 'adiantamento_sabado_quitado_em', None))

    if comissao_ja_adiantada_venda(venda):
        if sab_marcado and sab_quitado:
            return 'sabado_quitado_instalacao'
        if sab_marcado:
            return 'sabado'
        if sab_quitado:
            return 'sabado_quitado_instalacao'
        return 'esteira_comissao'

    if sab_marcado and not sab_quitado:
        return 'sabado_pendente'
    return None


def label_tipo_comissao_extrato(base_tipo: str | None, origem_adiant: str | None = None) -> str:
    """Rótulo legível para coluna TIPO COMISSÃO do extrato."""
    base = (base_tipo or '').lower()
    if base == 'a_pagar':
        return 'A pagar'
    if base == 'churn':
        return 'Churn (desconto)'
    if base == 'referencia':
        if origem_adiant == 'sabado_pendente':
            return 'Referência — adiant. sábado'
        return 'Referência (tabela)'
    if base == 'antecipada':
        return {
            'esteira_comissao': 'Antecipada — comissão (esteira)',
            'sabado': 'Antecipada — sábado',
            'sabado_quitado_instalacao': 'Antecipada — sábado (quitado na instalação)',
            'sabado_pendente': 'Antecipada — sábado',
        }.get(origem_adiant or '', 'Antecipada — comissão (esteira)')
    return '—'


def valor_comissao_linha_extrato(
    venda,
    *,
    faixa_regra,
    faixa_adiantamento,
    config,
    usar_manual,
    instalada_na_folha=False,
    churn_m1=False,
    complemento_sabado: float | None = None,
    valores_esteira_lancamento: dict[int, float] | None = None,
    matriz_cache=None,
    cidades_especiais_cache=None,
):
    """
    Valor e tipo de comissão exibidos no extrato por venda.
    Retorna (valor float|None, rótulo tipo comissão, código base).
    """
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao
    from crm_app.services.adiantamento_sabado_service import (
        comissao_ja_adiantada_venda,
        valor_pago_adiantamento_sabado_venda,
    )

    plano_nome = venda.plano.nome if venda.plano else ''
    chave = plano_tipo_to_chave(
        plano_nome,
        tipo_cliente_comissao(venda),
        venda=venda,
        cidades_especiais_cache=cidades_especiais_cache,
    )
    origem = origem_adiantamento_comissao_venda(venda)
    if not chave:
        val = None
        if origem in ('sabado', 'sabado_quitado_instalacao', 'sabado_pendente'):
            pago = valor_pago_adiantamento_sabado_venda(venda)
            if pago > 0:
                comp = float(complemento_sabado or 0)
                val = round(pago + comp, 2) if comp and origem != 'sabado_pendente' else pago
        base = 'antecipada' if comissao_ja_adiantada_venda(venda) else 'referencia'
        return val, label_tipo_comissao_extrato(base, origem), base

    tabela = valor_comissao_tabela_adiantamento(
        venda,
        faixa_adiantamento,
        chave,
        matriz_cache=matriz_cache,
        cidades_especiais_cache=cidades_especiais_cache,
    )
    val_adiant = valor_adiantamento_exibicao_folha(
        venda,
        faixa_adiantamento,
        chave,
        origem,
        complemento_sabado=complemento_sabado,
        valores_esteira_lancamento=valores_esteira_lancamento,
        matriz_cache=matriz_cache,
        cidades_especiais_cache=cidades_especiais_cache,
    )

    if churn_m1:
        vu = resolver_valor_comissao_venda(
            venda.plano,
            tipo_cliente_comissao(venda),
            faixa_regra=faixa_regra,
            config=config,
            usar_manual=usar_manual,
            chave=chave,
            matriz_cache=matriz_cache,
            venda=venda,
            cidades_especiais_cache=cidades_especiais_cache,
        )
        base = 'churn'
        return (float(vu) if vu is not None else tabela), label_tipo_comissao_extrato(base, origem), base

    if instalada_na_folha:
        if comissao_ja_adiantada_venda(venda):
            base = 'antecipada'
            label = label_tipo_comissao_extrato(base, origem)
            comp = float(complemento_sabado or 0)
            if comp > 0 and origem in ('sabado', 'sabado_quitado_instalacao'):
                label = f'{label} (+ complemento faixa)'
            elif comp < 0 and origem in ('sabado', 'sabado_quitado_instalacao'):
                label = f'{label} (ajuste rebaixa faixa)'
            return val_adiant, label, base
        vu = resolver_valor_comissao_venda(
            venda.plano,
            tipo_cliente_comissao(venda),
            faixa_regra=faixa_regra,
            config=config,
            usar_manual=usar_manual,
            chave=chave,
            matriz_cache=matriz_cache,
            venda=venda,
            cidades_especiais_cache=cidades_especiais_cache,
        )
        if vu is not None:
            base = 'a_pagar'
            return float(vu), label_tipo_comissao_extrato(base, origem), base
        base = 'referencia'
        return tabela, label_tipo_comissao_extrato(base, origem), base

    base = 'referencia'
    val_ref = val_adiant if origem == 'sabado_pendente' else tabela
    return val_ref, label_tipo_comissao_extrato(base, origem), base


def calcular_folha_mes(ano, mes, vendedor_id=None, use_effective_date_for_display=False):
    """
    Calcula a folha de comissão do mês no formato Excel.
    Mês de referência: data_instalacao_efetiva_folha (OSAB + física → usa física).
    use_effective_date_for_display: legado; o extrato usa sempre a data efetiva da folha em dt_inst.
    Retorna: {
      "periodo": "01/2026",
      "ano_mes": 202601,
      "vendedores": [
        {
          "vendedor_id", "vendedor_nome",
          "resumo": { "total_qtd_instalada_a_pagar", "por_plano": [...], "comissao_total_geral", "ajustes": {...}, "liquido" },
          "extrato": [ { "venda_id", "nome", "dacc", "cnpj", "plano", "dt_pedido", "dt_inst", "os", "situacao", "vendedor", "churn", "valor_comissao", "comissao_tipo" }, ... ]
        }
      ]
    }
    """
    from django.contrib.auth import get_user_model
    from .models import (
        Venda, RegraComissaoFaixa, ConfigComissaoVendedor,
        LancamentoFinanceiro, ImportacaoChurn,
    )

    User = get_user_model()

    def _norm_os(val):
        if val is None or (isinstance(val, str) and not val.strip()):
            return None
        s = str(val).strip()
        # Remover prefixos comuns (OS-, OS, etc.) para cruzar com base churn
        for prefix in ('OS-', 'OS', 'os-', 'os'):
            if s.upper().startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):].strip()
                break
        if not s:
            return None
        return s.zfill(8) if len(s) <= 8 else s

    def _norm_os_variantes(val):
        """Retorna variantes da O.S. para match (com zeros, sem zeros)."""
        n = _norm_os(val)
        if not n:
            return set()
        return {n, n.lstrip('0') or '0'}

    ano_mes = ano * 100 + mes
    mes_ant = (ano * 100 + mes - 1) if mes > 1 else ((ano - 1) * 100 + 12)
    # Aceitar anomes_gross em vários formatos (202512, 2025-12, 2025/12) para não falhar com imports antigos
    def _anomes_variantes(am):
        return [str(am), f"{am // 100}-{am % 100:02d}", f"{am // 100}/{am % 100:02d}"]
    variantes_m0 = _anomes_variantes(ano_mes)
    variantes_m1 = _anomes_variantes(mes_ant)
    churns_m0 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m0).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    churns_m1 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m1).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    set_os_churn_m0 = set()
    for os_val in churns_m0:
        if os_val is not None:
            set_os_churn_m0.update(_norm_os_variantes(str(os_val).strip()))
    set_os_churn_m1 = set()
    for os_val in churns_m1:
        if os_val is not None:
            set_os_churn_m1.update(_norm_os_variantes(str(os_val).strip()))
    set_os_churn_mes_extrato = set_os_churn_m0
    data_inicio = datetime(ano, mes, 1)
    if mes == 12:
        data_fim = datetime(ano + 1, 1, 1)
    else:
        data_fim = datetime(ano, mes + 1, 1)
    # Mês anterior (para M-1: churns instalados no mês anterior descontados na comissão deste mês)
    if mes == 1:
        data_inicio_ant = datetime(ano - 1, 12, 1)
        data_fim_ant = datetime(ano, 1, 1)
    else:
        data_inicio_ant = datetime(ano, mes - 1, 1)
        data_fim_ant = datetime(ano, mes, 1)

    consultores = User.objects.filter(is_active=True).select_related('perfil').order_by('username')
    if vendedor_id:
        consultores = consultores.filter(id=vendedor_id)
        if not consultores.exists():
            return {"periodo": f"{mes:02d}/{ano}", "ano_mes": ano * 100 + mes, "vendedores": []}

    # Regras por faixa: apenas finalidade COMISSAO (folha de pagamento). ADIANTAMENTO não entra aqui.
    from django.db.models import Q
    q_comissao = Q(finalidade='COMISSAO') | Q(finalidade__isnull=True)
    regras_faixa_perfil = list(
        RegraComissaoFaixa.objects.filter(q_comissao, vendedor__isnull=True).order_by('perfil', 'min_vendas')
    )
    regras_faixa_vendedor = defaultdict(list)
    for r in RegraComissaoFaixa.objects.filter(q_comissao, vendedor__isnull=False).select_related('vendedor'):
        regras_faixa_vendedor[r.vendedor_id].append(r)

    # Config do mês (ano, mes) com fallback para modelo padrão (ano/mes nulos)
    configs = {}
    for c in ConfigComissaoVendedor.objects.filter(ano=ano, mes=mes).select_related('usuario'):
        configs[c.usuario_id] = c
    for c in ConfigComissaoVendedor.objects.filter(ano__isnull=True, mes__isnull=True).select_related('usuario'):
        if c.usuario_id not in configs:
            configs[c.usuario_id] = c

    from crm_app.services.comissao_matriz_service import MatrizComissaoCache

    config_ids_matriz = [c.id for c in configs.values() if c]
    matriz_cache = MatrizComissaoCache.carregar(config_ids_matriz)
    from crm_app.services.comissao_cidade_especial_service import carregar_cidades_oferta_especial
    cidades_especiais_cache = carregar_cidades_oferta_especial()

    def _safe_min_max(r):
        """Evita comparação None > None no sorted e no intervalo."""
        min_v = r.min_vendas if r.min_vendas is not None else 0
        max_v = r.max_vendas if r.max_vendas is not None else (10 ** 9)
        return min_v, max_v

    def _normalizar_perfil_comissao(valor):
        v = (valor or '').strip().upper()
        if not v:
            return None
        if v == 'SUPERVISOR':
            return 'Supervisor'
        if v == 'VENDEDOR':
            return 'Vendedor'
        return None

    def _perfil_comissao_do_consultor(consultor, config):
        # Prioridade: perfil real do usuário -> regra do mês -> padrão Vendedor
        perfil_usuario = getattr(getattr(consultor, 'perfil', None), 'nome', None)
        perfil_resolvido = _normalizar_perfil_comissao(perfil_usuario)
        if perfil_resolvido:
            return perfil_resolvido
        perfil_config = _normalizar_perfil_comissao(getattr(config, 'perfil_comissao', None))
        if perfil_config:
            return perfil_config
        return 'Vendedor'

    def encontrar_faixa(consultor, qtd_vendas):
        # 1) Regra individual do vendedor
        listas = regras_faixa_vendedor.get(consultor.id, [])
        for r in sorted(listas, key=lambda x: _safe_min_max(x)[0], reverse=True):
            min_v, max_v = _safe_min_max(r)
            if min_v <= qtd_vendas <= max_v:
                return r
        # 2) Regra por perfil
        config = configs.get(consultor.id)
        perfil = _perfil_comissao_do_consultor(consultor, config)
        for r in regras_faixa_perfil:
            if r.perfil != perfil:
                continue
            min_v, max_v = _safe_min_max(r)
            if min_v <= qtd_vendas <= max_v:
                return r
        return None

    consultor_ids = list(consultores.values_list('id', flat=True))
    vendas_bulk_m0 = _agrupar_vendas_folha_bulk(consultor_ids, data_inicio, data_fim)
    vendas_bulk_m1 = _agrupar_vendas_folha_bulk(consultor_ids, data_inicio_ant, data_fim_ant)
    lancamentos_bulk = _agrupar_lancamentos_bulk(consultor_ids, data_inicio, data_fim)
    from crm_app.services.adiantamento_sabado_service import (
        carregar_valores_pago_sabado_lancamentos,
        comissao_ja_adiantada_venda,
        calcular_complemento_adiantamento_sabado_folha,
        valor_pago_adiantamento_sabado_venda,
        venda_entra_estorno_adiantamento_sabado_mes,
        venda_elegivel_estorno_adiantamento_sabado,
        motivo_estorno_adiantamento_sabado,
    )

    valores_pago_sabado_global = carregar_valores_pago_sabado_lancamentos()
    # Uma query para todos os vendedores (mapa venda_id → valor).
    valores_esteira_global = carregar_valores_adiantamento_esteira_lancamentos()

    # Faixas de adiantamento por perfil (2–3 queries no total, não por consultor).
    faixas_adiant_por_perfil: dict[str, object] = {}
    for perfil_nome in ('Vendedor', 'Supervisor'):
        faixas_adiant_por_perfil[perfil_nome] = carregar_faixa_adiantamento_regras_faixa(
            perfil=perfil_nome,
        )
    faixa_adiant_fallback = RegraComissaoFaixa.objects.filter(
        finalidade='COMISSAO',
    ).order_by('id').first()

    # Estornos/alertas de adiantamento sábado em bulk.
    descontos_sab_bulk: dict[int, list] = defaultdict(list)
    alertas_sab_bulk: dict[int, list] = defaultdict(list)
    di_sab = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df_sab = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    if di_sab and df_sab and consultor_ids:
        vendas_sab_qs = (
            Venda.objects.filter(
                vendedor_id__in=consultor_ids,
                ativo=True,
                adiantamento_sabado_marcado=True,
                flag_desc_adiantamento_sabado=False,
                adiantamento_sabado_quitado_em__isnull=True,
            )
            .exclude(adiantamento_sabado_valor__isnull=True)
            .exclude(adiantamento_sabado_valor=0)
            .select_related('status_esteira', 'cliente')
        )
        for v_sab in vendas_sab_qs:
            if venda_entra_estorno_adiantamento_sabado_mes(v_sab, di_sab, df_sab):
                val_sab = valor_pago_adiantamento_sabado_venda(v_sab, valores_pago_sabado_global)
                if val_sab > 0:
                    descontos_sab_bulk[v_sab.vendedor_id].append({
                        'venda_id': v_sab.id,
                        'valor': val_sab,
                        'motivo': motivo_estorno_adiantamento_sabado(v_sab),
                    })
            elif (
                getattr(v_sab, 'data_abertura', None) is None
                and venda_elegivel_estorno_adiantamento_sabado(v_sab)
            ):
                alertas_sab_bulk[v_sab.vendedor_id].append({
                    'tipo': 'adiantamento_sabado_sem_data_abertura',
                    'venda_id': v_sab.id,
                    'os': v_sab.ordem_servico or '',
                    'nome': (
                        (v_sab.cliente.nome_razao_social or '')[:80]
                        if getattr(v_sab, 'cliente', None)
                        else ''
                    ),
                    'situacao': (
                        (v_sab.status_esteira.nome or '')
                        if v_sab.status_esteira
                        else ''
                    ),
                    'mensagem': (
                        'Venda com adiantamento sábado sem data de abertura da O.S. '
                        '— corrija no cadastro para o estorno entrar na folha.'
                    ),
                })

    # Extrato: vendas do mês com status diferente de INSTALADA (1 query para todos).
    vendas_outros_bulk: dict[int, list] = defaultdict(list)
    if consultor_ids:
        for v_out in (
            Venda.objects.filter(
                vendedor_id__in=consultor_ids,
                ativo=True,
                data_criacao__gte=data_inicio,
                data_criacao__lt=data_fim,
            )
            .exclude(status_esteira__nome__iexact='INSTALADA')
            .select_related(
                'plano', 'plano__valores_comissao', 'cliente', 'forma_pagamento',
                'status_esteira', 'status_tratamento',
            )
            .order_by('vendedor_id', 'data_criacao', 'id')
        ):
            vendas_outros_bulk[v_out.vendedor_id].append(v_out)

    resultado = []
    for consultor in consultores:
        vendas = vendas_bulk_m0.get(consultor.id, [])
        vendas_m1 = vendas_bulk_m1.get(consultor.id, [])

        config = configs.get(consultor.id)
        # Adiant. Comissão = Sim na esteira: não entra em QTD A PAGAR nem na comissão do mês (já adiantada).

        set_adiant_comissao_esteira = {v.id for v in vendas if comissao_ja_adiantada_venda(v)}
        vendas_para_pagar = [v for v in vendas if v.id not in set_adiant_comissao_esteira]
        qtd_instalada_a_pagar = len(vendas_para_pagar)
        qtd_total_instalada = len(vendas)
        # Faixa pela produção total instalada no mês (antecipadas + a pagar), conforme regra de negócio.
        faixa_regra = encontrar_faixa(consultor, qtd_total_instalada)
        usar_manual = config and config.usar_valor_manual
        perfil_consultor = _perfil_comissao_do_consultor(consultor, config)
        faixa_adiantamento = (
            faixas_adiant_por_perfil.get(perfil_consultor) or faixa_adiant_fallback
        )
        valores_esteira_lanc = valores_esteira_global

        valores_pago_sabado_lanc = valores_pago_sabado_global
        resumo_complemento_sab = calcular_complemento_adiantamento_sabado_folha(
            vendas,
            faixa_regra_total=faixa_regra,
            config=config,
            usar_manual=bool(usar_manual),
            valores_lancamento=valores_pago_sabado_lanc,
            matriz_cache=matriz_cache,
            cidades_especiais_cache=cidades_especiais_cache,
        )
        complemento_por_venda = resumo_complemento_sab.get('por_venda') or {}
        complemento_sabado_total = Decimal(str(resumo_complemento_sab.get('total_complemento') or 0))

        # Por plano (chave): qtd a pagar, qtd antecipada (esteira), total já adiantado (pago sábado / esteira)
        por_plano = defaultdict(
            lambda: {
                'qtd': 0,
                'qtd_antecipada': 0,
                'valor_unit': None,
                'total': 0.0,
                'total_antecipado': 0.0,
                'total_complemento_sabado': 0.0,
            }
        )
        comissao_total_geral = Decimal('0')
        qtd_adiant_sem_chave_excel = 0
        valor_adiant_sem_chave_excel = 0.0
        info_adiantamento_origem = {
            'adiantamento_sabado': {'quantidade': 0, 'valor_total': 0.0},
            'adiantamento_sabado_quitado_instalacao': {'quantidade': 0, 'valor_total': 0.0},
            'adiantamento_esteira_instalados': {'quantidade': 0, 'valor_total': 0.0},
            'adiantamento_nao_classificado': {'quantidade': 0, 'valor_total': 0.0},
        }
        from crm_app.services.cnpj_mei_service import (
            CLASSIFICACAO_MEI,
            classificacao_mei_venda,
            tipo_cliente_comissao,
        )

        por_plano_cnpj_mei = defaultdict(int)
        qtd_cnpj_mei_total = 0
        qtd_cnpj_nmei_total = 0
        qtd_cpf_total = 0

        for v in vendas:
            tipo_cliente = tipo_cliente_comissao(v)
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(
                plano_nome,
                tipo_cliente,
                venda=v,
                cidades_especiais_cache=cidades_especiais_cache,
            )
            doc_limpo_v = ''.join(filter(str.isdigit, (v.cliente.cpf_cnpj or '') if v.cliente else ''))
            if len(doc_limpo_v) == 14:
                if classificacao_mei_venda(v) == CLASSIFICACAO_MEI:
                    qtd_cnpj_mei_total += 1
                    if chave:
                        por_plano_cnpj_mei[chave] += 1
                else:
                    qtd_cnpj_nmei_total += 1
            elif len(doc_limpo_v) == 11:
                qtd_cpf_total += 1
            if comissao_ja_adiantada_venda(v):
                o_ant = origem_adiantamento_comissao_venda(v) or 'esteira_comissao'
                comp_v = float((complemento_por_venda.get(v.id) or {}).get('complemento') or 0)
                va = valor_adiantamento_exibicao_folha(
                    v,
                    faixa_adiantamento,
                    chave,
                    o_ant,
                    complemento_sabado=comp_v,
                    valores_esteira_lancamento=valores_esteira_lanc,
                    matriz_cache=matriz_cache,
                )
                if chave:
                    por_plano[chave]['qtd_antecipada'] += 1
                    if o_ant in ('sabado', 'sabado_quitado_instalacao'):
                        pago_v = valor_pago_adiantamento_sabado_venda(v, valores_pago_sabado_lanc)
                        por_plano[chave]['total_antecipado'] += pago_v
                        por_plano[chave]['total_complemento_sabado'] += comp_v
                    else:
                        por_plano[chave]['total_antecipado'] += float(va or 0)
                else:
                    qtd_adiant_sem_chave_excel += 1
                    valor_adiant_sem_chave_excel += va
                if not chave:
                    chave_origem = 'adiantamento_nao_classificado'
                else:
                    _map_origem = {
                        'esteira_comissao': 'adiantamento_esteira_instalados',
                        'sabado': 'adiantamento_sabado',
                        'sabado_quitado_instalacao': 'adiantamento_sabado_quitado_instalacao',
                        'sabado_pendente': 'adiantamento_sabado',
                    }
                    o = origem_adiantamento_comissao_venda(v) or 'esteira_comissao'
                    chave_origem = _map_origem.get(o, 'adiantamento_nao_classificado')
                info_adiantamento_origem[chave_origem]['quantidade'] += 1
                ref_val = float(va or 0)
                if o_ant in ('sabado', 'sabado_quitado_instalacao', 'sabado_pendente'):
                    ref_val = valor_pago_adiantamento_sabado_venda(v, valores_pago_sabado_lanc)
                info_adiantamento_origem[chave_origem]['valor_total'] += ref_val
                continue
            if not chave:
                continue
            valor_unit = resolver_valor_comissao_venda(
                v.plano,
                tipo_cliente,
                faixa_regra=faixa_regra,
                config=config,
                usar_manual=usar_manual,
                chave=chave,
                matriz_cache=matriz_cache,
                venda=v,
                cidades_especiais_cache=cidades_especiais_cache,
                )
            valor_unit = valor_unit if valor_unit is not None else 0
            por_plano[chave]['qtd'] += 1
            por_plano[chave]['valor_unit'] = valor_unit
            por_plano[chave]['total'] += valor_unit
            comissao_total_geral += Decimal(str(valor_unit))

        # Montar lista por_plano (500 / 600 / 600 ESP / 700 / 1GB) + qtd_antecipada
        labels = LABELS_CHAVE_PLANO
        por_plano_lista = []
        for chave in CHAVES_PLANO:
            d = por_plano.get(
                chave,
                {
                    'qtd': 0,
                    'qtd_antecipada': 0,
                    'valor_unit': None,
                    'total': 0,
                    'total_antecipado': 0.0,
                    'total_complemento_sabado': 0.0,
                },
            )
            comp_plano = round(float(d.get('total_complemento_sabado', 0) or 0), 2)
            pago_plano = round(float(d.get('total_antecipado', 0) or 0), 2)
            por_plano_lista.append({
                'plano': labels.get(chave, chave),
                'qtd_instalada_a_pagar': d['qtd'],
                'qtd_cnpj_mei': por_plano_cnpj_mei.get(chave, 0),
                'qtd_antecipada': d.get('qtd_antecipada', 0),
                'valor_total_antecipado': pago_plano,
                'valor_total_complemento_sabado': comp_plano,
                'valor_total_venda_sabado': round(pago_plano + comp_plano, 2),
                'qtd_ja_pago': 0,
                'qtd_churn_30': 0,
                'valor_unitario_instalados': d['valor_unit'],
                'valor_unitario_churn': None,
                'valor_total_instalados': round(d['total'], 2),
                'valor_total_churn': 0,
                'comissao_total': round(d['total'], 2),
            })

        # Ajustes: descontos vêm dos lançamentos confirmados (Adiantamentos e Descontos / Confirmar Descontos) + config (INSS, etc.)
        # Não somar por venda da config: boleto/inclusão/instalação/adiant.CNPJ só entram após confirmação (LancamentoFinanceiro).
        lancamentos = lancamentos_bulk.get(consultor.id, [])
        total_descontos = Decimal('0')
        detalhes_descontos = []
        detalhes_bonus_lancamentos = []
        for l in lancamentos:
            if getattr(l, 'tipo', None) == 'BONUS_PREMIACAO':
                motivo_bp = (l.descricao or '').strip() or 'Bônus/Premiação'
                detalhes_bonus_lancamentos.append(
                    {'motivo': motivo_bp, 'valor': float(l.valor)}
                )
                continue
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_COMISSAO':
                # Folha usa apenas a marcação na esteira + primeira faixa COMISSAO; não é desconto.
                continue
            qtd = getattr(l, 'quantidade_vendas', None) or 1
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_CNPJ':
                venda_ids_cnpj = (l.metadados or {}).get('venda_ids') or []
                if venda_ids_cnpj:
                    qtd = len(venda_ids_cnpj)
            desc = (l.descricao or l.get_tipo_display() or 'Desconto')
            # Exibir desconto direto (sem "Processamento Auto:") e classificar para separar boleto / adiant. CNPJ / adiant. comissão
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_CNPJ':
                motivo_limpo = 'Adiant. CNPJ'
            elif desc.startswith('Processamento Auto:'):
                resto = desc.replace('Processamento Auto:', '').strip()
                mapa = {
                    'BOLETO': 'Desconto Boleto',
                    'CNPJ': 'Adiant. CNPJ',
                    'VIABILIDADE': 'Desconto Inclusão',
                    'ANTECIPACAO': 'Desconto Antecipação',
                    'ADIANT_SABADO': 'Desconto adiantamento sábado',
                }
                partes = [mapa.get(p.strip(), p.strip()) for p in resto.split(',') if p.strip()]
                motivo_limpo = ', '.join(partes) if partes else resto
            else:
                motivo_limpo = desc
            # tipo_exibicao: boleto | adiant_cnpj | adiant_comissao | outros (para agrupar na UI)
            lt = getattr(l, 'tipo', None)
            if lt == 'ADIANTAMENTO_CNPJ':
                tipo_exibicao = 'adiant_cnpj'
            else:
                tipo_exibicao = 'outros'
            if tipo_exibicao == 'outros' and desc.startswith('Processamento Auto:'):
                ru = desc.upper()
                has_boleto = 'BOLETO' in ru
                has_cnpj = 'CNPJ' in ru
                has_ant = 'ANTECIPACAO' in ru
                if has_cnpj:
                    tipo_exibicao = 'adiant_cnpj'
                elif has_boleto and has_ant:
                    tipo_exibicao = 'processamento_auto_misto'
                elif has_boleto:
                    tipo_exibicao = 'boleto'
                elif has_ant:
                    tipo_exibicao = 'antecipacao_instalacao'
            # Boleto/antecipação/misto entram só pelo cálculo do mês (abaixo), não pelo lançamento automático
            if tipo_exibicao in ('boleto', 'antecipacao_instalacao', 'processamento_auto_misto'):
                continue
            total_descontos += l.valor
            detalhes_descontos.append(
                {
                    'motivo': motivo_limpo,
                    'valor': float(l.valor),
                    'tipo_exibicao': tipo_exibicao,
                    'quantidade': qtd,
                }
            )
        if config:
            if config.inss_valor and float(config.inss_valor) > 0:
                total_descontos += config.inss_valor
                detalhes_descontos.append({'motivo': 'INSS / Encargos', 'valor': float(config.inss_valor), 'tipo_exibicao': 'outros', 'quantidade': 1})
            if config.adiantamento and float(config.adiantamento) > 0:
                total_descontos += config.adiantamento
                detalhes_descontos.append({'motivo': 'Adiantamento', 'valor': float(config.adiantamento), 'tipo_exibicao': 'outros', 'quantidade': 1})
            if config.cartao_trafego and float(config.cartao_trafego) > 0:
                total_descontos += config.cartao_trafego
                detalhes_descontos.append({'motivo': 'Cartão Tráfego', 'valor': float(config.cartao_trafego), 'tipo_exibicao': 'outros', 'quantidade': 1})
            if config.gestor_trafego and float(config.gestor_trafego) > 0:
                total_descontos += config.gestor_trafego
                detalhes_descontos.append({'motivo': 'Gestor Tráfego', 'valor': float(config.gestor_trafego), 'tipo_exibicao': 'outros', 'quantidade': 1})

        # Desconto Churn M0 e M-1: cruza base churn (ANOMES_GROSS) com Venda por O.S.; só Vendas ainda não marcadas com desconto_churn_aplicado_em
        # M0 = churns do mês da comissão (ex.: jan/26) -> vendas instaladas no mês da comissão
        # M-1 = churns do mês anterior (ex.: dez/25) -> descontado na comissão do mês atual (jan/26); vendas instaladas no mês anterior
        valor_churn_m0 = Decimal('0')
        valor_churn_m1 = Decimal('0')
        qtd_churn_m0 = 0
        qtd_churn_m1 = 0
        for v in vendas:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
            from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

            tipo_cliente = tipo_cliente_comissao(v)
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(
                plano_nome,
                tipo_cliente,
                venda=v,
                cidades_especiais_cache=cidades_especiais_cache,
            )
            if not chave:
                continue
            valor_unit = resolver_valor_comissao_venda(
                v.plano,
                tipo_cliente,
                faixa_regra=faixa_regra,
                config=config,
                usar_manual=usar_manual,
                chave=chave,
                matriz_cache=matriz_cache,
                venda=v,
                cidades_especiais_cache=cidades_especiais_cache,
                )
            valor_unit = Decimal(str(valor_unit)) if valor_unit is not None else Decimal('0')
            if variantes & set_os_churn_m0:
                valor_churn_m0 += valor_unit
                qtd_churn_m0 += 1
        for v in vendas_m1:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
            if not (variantes & set_os_churn_m1):
                continue
            from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

            tipo_cliente = tipo_cliente_comissao(v)
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(
                plano_nome,
                tipo_cliente,
                venda=v,
                cidades_especiais_cache=cidades_especiais_cache,
            )
            if not chave:
                continue
            valor_unit = resolver_valor_comissao_venda(
                v.plano,
                tipo_cliente,
                faixa_regra=faixa_regra,
                config=config,
                usar_manual=usar_manual,
                chave=chave,
                matriz_cache=matriz_cache,
                venda=v,
                cidades_especiais_cache=cidades_especiais_cache,
                )
            valor_unit = Decimal(str(valor_unit)) if valor_unit is not None else Decimal('0')
            valor_churn_m1 += valor_unit
            qtd_churn_m1 += 1
        if qtd_churn_m0 > 0 or valor_churn_m0 > 0:
            total_descontos += valor_churn_m0
            detalhes_descontos.append({'motivo': 'Desconto Churn M0', 'valor': float(valor_churn_m0), 'tipo_exibicao': 'churn_m0', 'quantidade': qtd_churn_m0})
        if qtd_churn_m1 > 0 or valor_churn_m1 > 0:
            total_descontos += valor_churn_m1
            detalhes_descontos.append({'motivo': 'Desconto Churn M-1', 'valor': float(valor_churn_m1), 'tipo_exibicao': 'churn_m1', 'quantidade': qtd_churn_m1})

        # Boleto: CPF e CNPJ MEI instalados no mês (inclui sábado quitado; exclui comissão antecipada na esteira). NMEI isento.
        # "Desconta Boleto PAP?" vem da Config. Comissão do mês em Regras por vendedor (vale também com comissão manual).
        from crm_app.services.cnpj_mei_service import elegivel_desconto_boleto_folha

        desconta_boleto_pap = bool(getattr(config, 'desconta_boleto_pap', True)) if config else True
        qtd_vendas_boleto_mes = sum(1 for v in vendas if elegivel_desconto_boleto_folha(v))
        qtd_vendas_antecip_mes = sum(1 for v in vendas if getattr(v, 'antecipou_instalacao', False))
        unit_bo = float(getattr(consultor, 'desconto_boleto', None) or 0)
        unit_ant = float(getattr(consultor, 'desconto_instalacao_antecipada', None) or 0)
        valor_boleto_cheio = (Decimal(str(unit_bo)) * qtd_vendas_boleto_mes).quantize(Decimal('0.01'))
        valor_ant_cheio = (Decimal(str(unit_ant)) * qtd_vendas_antecip_mes).quantize(Decimal('0.01'))
        valor_boleto_efetivo = valor_boleto_cheio if desconta_boleto_pap else Decimal('0')
        if qtd_vendas_boleto_mes > 0:
            total_descontos += valor_boleto_efetivo
            detalhes_descontos.append(
                {
                    'motivo': 'Descontos vendas no boleto',
                    'valor': float(valor_boleto_cheio),
                    'tipo_exibicao': 'folha_boleto_vendas',
                    'quantidade': qtd_vendas_boleto_mes,
                }
            )
        if qtd_vendas_antecip_mes > 0:
            total_descontos += valor_ant_cheio
            detalhes_descontos.append(
                {
                    'motivo': 'Desconto antecipação de instalação',
                    'valor': float(valor_ant_cheio),
                    'tipo_exibicao': 'folha_antecipacao_instalacao',
                    'quantidade': qtd_vendas_antecip_mes,
                }
            )

        # Adiantamento sábado: estorno na folha do mês da abertura da O.S. (safra).
        descontos_sab = descontos_sab_bulk.get(consultor.id, [])
        alertas_folha = alertas_sab_bulk.get(consultor.id, [])
        valor_sab_cancel = Decimal('0')
        qtd_sab_cancel = 0
        motivos_sab = {}
        for item in descontos_sab:
            val_sab = Decimal(str(item['valor']))
            if val_sab <= 0:
                continue
            valor_sab_cancel += val_sab
            qtd_sab_cancel += 1
            motivos_sab[item['motivo']] = motivos_sab.get(item['motivo'], 0) + 1
        if qtd_sab_cancel > 0:
            total_descontos += valor_sab_cancel
            for motivo, qtd in motivos_sab.items():
                val_motivo = sum(
                    Decimal(str(x['valor']))
                    for x in descontos_sab
                    if x['motivo'] == motivo
                )
                detalhes_descontos.append(
                    {
                        'motivo': motivo,
                        'valor': float(val_motivo),
                        'tipo_exibicao': 'folha_adiant_sabado_cancel',
                        'quantidade': qtd,
                    }
                )

        total_bonus = Decimal('0')
        detalhes_bonus = []
        if config:
            prem = getattr(config, 'premiação', None) or 0
            prem_dec = Decimal(str(prem)) if prem else Decimal('0')
            if prem_dec > 0:
                detalhes_bonus.append(
                    {
                        'motivo': 'Premiação (Regras por vendedor)',
                        'valor': float(prem_dec),
                    }
                )
                total_bonus += prem_dec
            bcc = config.bonus_cartao_credito or 0
            bcc_dec = Decimal(str(bcc)) if bcc else Decimal('0')
            if bcc_dec > 0:
                detalhes_bonus.append(
                    {
                        'motivo': 'Bônus cartão crédito (Regras por vendedor)',
                        'valor': float(bcc_dec),
                    }
                )
                total_bonus += bcc_dec
        for item in detalhes_bonus_lancamentos:
            total_bonus += Decimal(str(item['valor']))
            detalhes_bonus.append(item)

        liquido = comissao_total_geral + complemento_sabado_total + total_bonus - total_descontos
        # Badge/origem: com valor manual ativo a grade da folha NÃO usa a tabela de faixas.
        faixa_referencia = (faixa_regra.faixa_nome if faixa_regra else None) or ''
        if usar_manual:
            faixa_aplicada = 'Regras por vendedor'
        else:
            faixa_aplicada = faixa_referencia
        faixa_complemento_sabado = faixa_referencia or faixa_aplicada
        origem_valores = 'manual' if usar_manual else 'faixa'

        ajustes = {
            'premiacao': float(getattr(config, 'premiação', None) or 0) if config else 0,
            'instalacao': 0,
            'adiantar_cnpj': 0,
            'desconto_boleto': 0,
            'gestor_trafego': float(config.gestor_trafego) if config and config.gestor_trafego else 0,
            'cartao_trafego': float(config.cartao_trafego) if config and config.cartao_trafego else 0,
            'adiantar_mes': 0,
            'churn_ate_30_dias': 0,
            'churn_acima_30_dias': 0,
        }
        if config:
            ajustes['desconto_boleto'] = float(config.desconto_boleto or 0)
            ajustes['adiantar_cnpj'] = float(config.adiantar_cnpj or 0)
            ajustes['instalacao'] = float(config.desconto_instalacao or 0)

        from crm_app.services.cnpj_mei_service import classificacao_mei_venda, tipo_cliente_comissao

        def _campos_extrato_mei(venda):
            doc = (venda.cliente.cpf_cnpj or '') if venda.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            eh_cnpj = len(doc_limpo) == 14
            plano_nome = venda.plano.nome if venda.plano else ''
            chave = plano_tipo_to_chave(
                plano_nome,
                tipo_cliente_comissao(venda),
                venda=venda,
                cidades_especiais_cache=cidades_especiais_cache,
            )
            mei = classificacao_mei_venda(venda) if eh_cnpj else None
            return {
                'plano_label': labels.get(chave, plano_nome or '-'),
                'cnpj': 'SIM' if eh_cnpj else 'NÃO',
                'classificacao_mei': mei if mei else '-',
            }

        extrato = []
        for v in vendas:
            campos = _campos_extrato_mei(v)
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            churn_status = 'SIM' if _norm_os_variantes(v.ordem_servico) & set_os_churn_mes_extrato else 'NÃO'
            dt_inst = getattr(v, 'data_folha_comissao', None) or data_instalacao_efetiva_folha(v)
            val_com, tipo_com_label, tipo_com_cod = valor_comissao_linha_extrato(
                v,
                faixa_regra=faixa_regra,
                faixa_adiantamento=faixa_adiantamento,
                config=config,
                usar_manual=usar_manual,
                instalada_na_folha=True,
                complemento_sabado=float((complemento_por_venda.get(v.id) or {}).get('complemento') or 0),
                valores_esteira_lancamento=valores_esteira_lanc,
                matriz_cache=matriz_cache,
                cidades_especiais_cache=cidades_especiais_cache,
            )
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': campos['cnpj'],
                'classificacao_mei': campos['classificacao_mei'],
                'plano': campos['plano_label'],
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': dt_inst.strftime('%d/%m/%Y') if dt_inst else '',
                'os': v.ordem_servico or '',
                'situacao': (
                    v.status_esteira.nome
                    if v.status_esteira
                    else (v.status_tratamento.nome if getattr(v, 'status_tratamento', None) else 'INSTALADA')
                ),
                'vendedor': consultor.username,
                'churn': churn_status,
                'adiantada': 'SIM' if comissao_ja_adiantada_venda(v) else 'NÃO',
                'valor_comissao': round(float(val_com), 2) if val_com is not None else None,
                'comissao_tipo': tipo_com_label,
                'comissao_tipo_codigo': tipo_com_cod,
            })
        # Incluir no extrato as vendas churn M-1 (mês anterior), para aparecerem na lista com CHURN=SIM
        for v in vendas_m1:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
            if not (variantes & set_os_churn_m1):
                continue
            campos = _campos_extrato_mei(v)
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            dt_inst_m1 = getattr(v, 'data_folha_comissao', None) or data_instalacao_efetiva_folha(v)
            val_com, tipo_com_label, tipo_com_cod = valor_comissao_linha_extrato(
                v,
                faixa_regra=faixa_regra,
                faixa_adiantamento=faixa_adiantamento,
                config=config,
                usar_manual=usar_manual,
                churn_m1=True,
                matriz_cache=matriz_cache,
                cidades_especiais_cache=cidades_especiais_cache,
                )
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': campos['cnpj'],
                'classificacao_mei': campos['classificacao_mei'],
                'plano': campos['plano_label'],
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': dt_inst_m1.strftime('%d/%m/%Y') if dt_inst_m1 else '',
                'os': v.ordem_servico or '',
                'situacao': 'INSTALADA (Churn M-1)',
                'vendedor': consultor.username,
                'churn': 'SIM',
                'adiantada': 'NÃO',
                'valor_comissao': round(float(val_com), 2) if val_com is not None else None,
                'comissao_tipo': tipo_com_label,
                'comissao_tipo_codigo': tipo_com_cod,
            })
        # Após a listagem de instaladas (como já existe hoje), incluir também as vendas
        # criadas no mês com status diferente de INSTALADA.
        for v in vendas_outros_bulk.get(consultor.id, []):
            campos = _campos_extrato_mei(v)
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            status_nome = (
                v.status_esteira.nome
                if v.status_esteira
                else (v.status_tratamento.nome if getattr(v, 'status_tratamento', None) else '-')
            )
            val_com, tipo_com_label, tipo_com_cod = valor_comissao_linha_extrato(
                v,
                faixa_regra=faixa_regra,
                faixa_adiantamento=faixa_adiantamento,
                config=config,
                usar_manual=usar_manual,
                instalada_na_folha=False,
                matriz_cache=matriz_cache,
                cidades_especiais_cache=cidades_especiais_cache,
                )
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': campos['cnpj'],
                'classificacao_mei': campos['classificacao_mei'],
                'plano': campos['plano_label'],
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': '',
                'os': v.ordem_servico or '',
                'situacao': status_nome,
                'vendedor': consultor.username,
                'churn': 'NÃO',
                'adiantada': 'NÃO',
                'valor_comissao': round(float(val_com), 2) if val_com is not None else None,
                'comissao_tipo': tipo_com_label,
                'comissao_tipo_codigo': tipo_com_cod,
            })

        qtd_a_descontar_boleto = sum(
            d.get('quantidade', 1)
            for d in detalhes_descontos
            if (d.get('tipo_exibicao') or '').lower() == 'folha_boleto_vendas'
        )
        qtd_a_descontar_antecip = sum(
            d.get('quantidade', 1)
            for d in detalhes_descontos
            if (d.get('tipo_exibicao') or '').lower() == 'folha_antecipacao_instalacao'
        )
        qtd_a_descontar_sab_cancel = sum(
            d.get('quantidade', 1)
            for d in detalhes_descontos
            if (d.get('tipo_exibicao') or '').lower() == 'folha_adiant_sabado_cancel'
        )
        qtd_a_descontar_cnpj = sum(d.get('quantidade', 1) for d in detalhes_descontos if (d.get('tipo_exibicao') or '').lower() == 'adiant_cnpj')
        qtd_a_descontar = (
            qtd_a_descontar_boleto
            + qtd_a_descontar_antecip
            + qtd_a_descontar_sab_cancel
            + qtd_a_descontar_cnpj
            + qtd_churn_m0
            + qtd_churn_m1
        )

        tot_q_adiant = sum(int(x.get('qtd_antecipada', 0) or 0) for x in por_plano_lista) + qtd_adiant_sem_chave_excel
        tot_q_pagar_antecip = int(qtd_instalada_a_pagar) + int(tot_q_adiant)
        tot_v_adiant = sum(float(x.get('valor_total_antecipado', 0) or 0) for x in por_plano_lista) + float(
            valor_adiant_sem_chave_excel
        )
        info_por_plano_adiant = [
            {
                'plano': x['plano'],
                'qtd': int(x.get('qtd_antecipada', 0) or 0),
                'valor_total': float(x.get('valor_total_antecipado', 0) or 0),
            }
            for x in por_plano_lista
            if (x.get('qtd_antecipada', 0) or 0) > 0
        ]
        if qtd_adiant_sem_chave_excel > 0:
            info_por_plano_adiant.append(
                {
                    'plano': 'Plano fora da grade (fallback)',
                    'qtd': qtd_adiant_sem_chave_excel,
                    'valor_total': round(valor_adiant_sem_chave_excel, 2),
                }
            )
        info_comissao_adiantada = {
            'quantidade_total': int(tot_q_adiant),
            'valor_total': round(tot_v_adiant, 2),
            'por_plano': info_por_plano_adiant,
            'por_origem': {
                k: {
                    'quantidade': int(v['quantidade']),
                    'valor_total': round(float(v['valor_total']), 2),
                }
                for k, v in info_adiantamento_origem.items()
            },
            'complemento_sabado': {
                'quantidade': int(resumo_complemento_sab.get('quantidade_complemento') or 0),
                'valor_complemento': round(float(resumo_complemento_sab.get('total_complemento') or 0), 2),
                'valor_pago': round(float(resumo_complemento_sab.get('total_pago') or 0), 2),
                'valor_alvo': round(float(resumo_complemento_sab.get('total_alvo') or 0), 2),
                'faixa_nome': resumo_complemento_sab.get('faixa_nome'),
                'detalhes_vendas': resumo_complemento_sab.get('detalhes') or [],
            },
        }
        detalhes_complemento_sabado = list(resumo_complemento_sab.get('detalhes') or [])
        if float(complemento_sabado_total) != 0 and not detalhes_complemento_sabado:
            qtd_comp = int(resumo_complemento_sab.get('quantidade_complemento') or 0)
            detalhes_complemento_sabado.append(
                {
                    'motivo': 'Complemento adiantamento sábado (faixa alcançada)',
                    'valor': float(complemento_sabado_total),
                    'quantidade': qtd_comp,
                }
            )

        resultado.append({
            'vendedor_id': consultor.id,
            'vendedor_nome': consultor.username,
            'resumo': {
                'total_qtd_instalada_a_pagar': qtd_instalada_a_pagar,
                'total_qtd_instalada_antecipada': int(tot_q_adiant),
                'total_qtd_vendas_folha': tot_q_pagar_antecip,
                'total_qtd_ja_pago': 0,
                'total_qtd_churn_30': 0,
                'faixa_aplicada': faixa_aplicada,
                'faixa_referencia': faixa_referencia,
                'origem_valores': origem_valores,
                'faixa_complemento_sabado': faixa_complemento_sabado,
                'qtd_instalada_faixa_complemento': qtd_total_instalada,
                'por_plano': por_plano_lista,
                'comissao_total_geral': float(comissao_total_geral),
                'complemento_sabado_total': float(complemento_sabado_total),
                'detalhes_complemento_sabado': detalhes_complemento_sabado,
                'ajustes': ajustes,
                'total_descontos': float(total_descontos),
                'total_bonus': float(total_bonus),
                'liquido': float(liquido),
                'detalhes_bonus': detalhes_bonus,
                'detalhes_descontos': detalhes_descontos,
                'desconta_boleto_pap': desconta_boleto_pap,
                'qtd_a_descontar': qtd_a_descontar,
                'qtd_a_descontar_boleto': qtd_a_descontar_boleto,
                'qtd_a_descontar_antecip': qtd_a_descontar_antecip,
                'qtd_a_descontar_cnpj': qtd_a_descontar_cnpj,
                'info_comissao_adiantada': info_comissao_adiantada,
                'cnpj_comissao_visual': {
                    'qtd_cpf': qtd_cpf_total,
                    'qtd_cnpj_mei': qtd_cnpj_mei_total,
                    'qtd_cnpj_nmei': qtd_cnpj_nmei_total,
                },
                'alertas_folha': alertas_folha,
            },
            'extrato': extrato,
        })

    return {
        'periodo': f"{mes:02d}/{ano}",
        'ano_mes': ano * 100 + mes,
        'vendedores': resultado,
    }


def get_vendas_ids_desconto_churn_mes(ano, mes):
    """
    Retorna os IDs das Vendas que entram no desconto churn (M0 + M-1) para o mês de comissão (ano, mes).
    M0: vendas instaladas no mês da comissão que batem com churn do mês. M-1: vendas instaladas no mês anterior que batem com churn M-1.
    Usado ao fechar o mês para marcar desconto_churn_aplicado_em e não descontar duas vezes.
    """
    from .models import Venda, ImportacaoChurn

    def _norm_os_variantes(val):
        if val is None or (isinstance(val, str) and not val.strip()):
            return set()
        s = str(val).strip()
        for prefix in ('OS-', 'OS', 'os-', 'os'):
            if s.upper().startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):].strip()
                break
        if not s:
            return set()
        n = s.zfill(8) if len(s) <= 8 else s
        return {n, n.lstrip('0') or '0'}

    ano_mes = ano * 100 + mes
    mes_ant = (ano * 100 + mes - 1) if mes > 1 else ((ano - 1) * 100 + 12)
    variantes_m0 = [str(ano_mes), f"{ano_mes // 100}-{ano_mes % 100:02d}", f"{ano_mes // 100}/{ano_mes % 100:02d}"]
    variantes_m1 = [str(mes_ant), f"{mes_ant // 100}-{mes_ant % 100:02d}", f"{mes_ant // 100}/{mes_ant % 100:02d}"]
    churns_m0 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m0).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    churns_m1 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m1).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    set_os_m0 = set()
    for os_val in churns_m0:
        set_os_m0.update(_norm_os_variantes(os_val))
    set_os_m1 = set()
    for os_val in churns_m1:
        set_os_m1.update(_norm_os_variantes(os_val))

    data_inicio = datetime(ano, mes, 1)
    data_fim = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)
    data_inicio_ant = datetime(ano, mes - 1, 1) if mes > 1 else datetime(ano - 1, 12, 1)
    data_fim_ant = datetime(ano, mes, 1) if mes > 1 else datetime(ano, 1, 1)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    consultores = list(User.objects.filter(is_active=True).values_list('id', flat=True))

    ids_marcar = []
    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    dia = data_inicio_ant.date() if hasattr(data_inicio_ant, 'date') else data_inicio_ant
    dfa = data_fim_ant.date() if hasattr(data_fim_ant, 'date') else data_fim_ant
    # M0: vendas instaladas no mês da comissão que batem com churn do mês
    base_m0 = Venda.objects.filter(
        vendedor_id__in=consultores,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
        desconto_churn_aplicado_em__isnull=True,
    ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
    vendas_m0 = annotate_data_folha_comissao(base_m0).filter(
        data_folha_comissao__isnull=False,
        data_folha_comissao__gte=di,
        data_folha_comissao__lt=df,
    ).only('id', 'ordem_servico', 'data_instalacao', 'data_instalacao_fisica')
    for v in vendas_m0:
        if _norm_os_variantes(v.ordem_servico) & set_os_m0:
            ids_marcar.append(v.id)
    # M-1: vendas instaladas no mês anterior que batem com churn M-1 (ex.: dez/25 descontado em jan/26)
    base_m1 = Venda.objects.filter(
        vendedor_id__in=consultores,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
        desconto_churn_aplicado_em__isnull=True,
    ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
    vendas_m1 = annotate_data_folha_comissao(base_m1).filter(
        data_folha_comissao__isnull=False,
        data_folha_comissao__gte=dia,
        data_folha_comissao__lt=dfa,
    ).only('id', 'ordem_servico', 'data_instalacao', 'data_instalacao_fisica')
    for v in vendas_m1:
        if _norm_os_variantes(v.ordem_servico) & set_os_m1:
            ids_marcar.append(v.id)
    return ids_marcar
