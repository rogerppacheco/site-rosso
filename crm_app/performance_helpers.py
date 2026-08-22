"""Helpers compartilhados: cores e ordenação do relatório de performance (painel / WhatsApp)."""
from collections import defaultdict
from datetime import date

from core.services.calendario_fiscal_service import TipoPesoFiscal

# Paleta por índice de faixa (0 = 1ª faixa atingida). Abaixo da 1ª faixa usa cores_linha_performance(0).
PALETA_FAIXAS_CORES = [
    ((255, 243, 205), (102, 77, 3)),
    ((255, 228, 156), (120, 72, 0)),
    ((207, 226, 255), (8, 66, 152)),
    ((13, 110, 253), (255, 255, 255)),
    ((20, 108, 67), (255, 255, 255)),
    ((25, 135, 84), (255, 255, 255)),
]


def ordem_cluster_performance(cluster):
    """CLUSTER_1 → 1, CLUSTER_2 → 2, CLUSTER_3 → 3; demais por último."""
    if not cluster:
        return 99
    c = str(cluster).strip().upper().replace(' ', '_')
    if c in ('CLUSTER_1', 'CLUSTER1', '1'):
        return 1
    if c in ('CLUSTER_2', 'CLUSTER2', '2'):
        return 2
    if c in ('CLUSTER_3', 'CLUSTER3', '3'):
        return 3
    return 99


def cores_linha_performance(total):
    """
    Faixas de vendas diárias (aba Hoje / média semanal):
    0 vermelho | 1-2 amarelo | 3-5 azul | 6+ verde escuro.
    Retorna (cor_fundo_rgb, cor_texto_rgb).
    """
    n = int(total or 0)
    if n == 0:
        return (248, 215, 218), (132, 32, 41)
    if n <= 2:
        return (255, 243, 205), (102, 77, 3)
    if n <= 5:
        return (207, 226, 255), (8, 66, 152)
    return (20, 108, 67), (255, 255, 255)


def cores_linha_por_indice_faixa(indice_faixa):
    """indice_faixa: -1 = abaixo da 1ª faixa; 0+ = faixa atingida (ordenada por min_vendas)."""
    if indice_faixa is None or indice_faixa < 0:
        return cores_linha_performance(0)
    idx = min(int(indice_faixa), len(PALETA_FAIXAS_CORES) - 1)
    return PALETA_FAIXAS_CORES[idx]


def dias_decorridos_semana(inicio_semana, fim_semana, hoje_ref):
    """Dias úteis decorridos na semana (Seg até hoje ou fim da semana), máx. 6."""
    if hoje_ref > fim_semana:
        return 6
    if hoje_ref < inicio_semana:
        return 1
    return min(6, (hoje_ref - inicio_semana).days + 1)


def media_diaria_semana_referencia(total_semana, dias_decorridos):
    """Média para comparar com faixas do dia; arredondamento matemático."""
    dias = max(1, int(dias_decorridos or 1))
    return int(round(float(total_semana or 0) / dias))


def cores_linha_semanal(total_semana, dias_decorridos):
    """Cores da aba semanal: média diária com mesmas faixas de Hoje."""
    ref = media_diaria_semana_referencia(total_semana, dias_decorridos)
    return cores_linha_performance(ref)


def _safe_min_max_regra(regra):
    min_v = regra.min_vendas if getattr(regra, 'min_vendas', None) is not None else 0
    max_v = regra.max_vendas if getattr(regra, 'max_vendas', None) is not None else (10 ** 9)
    return int(min_v), int(max_v)


def _safe_min_max_dict(regra):
    min_v = regra.get('min_vendas')
    max_v = regra.get('max_vendas')
    min_v = 0 if min_v is None else int(min_v)
    max_v = 10 ** 9 if max_v is None else int(max_v)
    return min_v, max_v


def normalizar_perfil_comissao(valor):
    v = (valor or '').strip().upper()
    if not v:
        return None
    if v == 'SUPERVISOR':
        return 'Supervisor'
    if v == 'VENDEDOR':
        return 'Vendedor'
    return None


def perfil_comissao_do_consultor(consultor, config):
    """Mesma prioridade da folha: perfil do usuário → config do mês → Vendedor."""
    perfil_usuario = getattr(getattr(consultor, 'perfil', None), 'nome', None)
    perfil_resolvido = normalizar_perfil_comissao(perfil_usuario)
    if perfil_resolvido:
        return perfil_resolvido
    perfil_config = normalizar_perfil_comissao(getattr(config, 'perfil_comissao', None) if config else None)
    if perfil_config:
        return perfil_config
    return 'Vendedor'


def carregar_contexto_faixas_comissao(ano=None, mes=None):
    """
    Regras COMISSAO + configs do mês (com fallback padrão).
    Retorna dict com regras_perfil, regras_vendedor (id -> list), configs (id -> config).
    """
    from django.db.models import Q

    from .models import ConfigComissaoVendedor, RegraComissaoFaixa

    q_comissao = Q(finalidade='COMISSAO') | Q(finalidade__isnull=True)
    regras_perfil = list(
        RegraComissaoFaixa.objects.filter(q_comissao, vendedor__isnull=True).order_by('perfil', 'min_vendas')
    )
    regras_vendedor = defaultdict(list)
    for r in RegraComissaoFaixa.objects.filter(q_comissao, vendedor__isnull=False).select_related('vendedor'):
        regras_vendedor[r.vendedor_id].append(r)

    configs = {}
    if ano is not None and mes is not None:
        for c in ConfigComissaoVendedor.objects.filter(ano=ano, mes=mes).select_related('usuario'):
            configs[c.usuario_id] = c
    for c in ConfigComissaoVendedor.objects.filter(ano__isnull=True, mes__isnull=True).select_related('usuario'):
        if c.usuario_id not in configs:
            configs[c.usuario_id] = c

    return {
        'regras_perfil': regras_perfil,
        'regras_vendedor': dict(regras_vendedor),
        'configs': configs,
    }


def _regras_aplicaveis_vendedor(ctx, usuario_id, perfil):
    individuais = ctx.get('regras_vendedor', {}).get(usuario_id) or []
    if individuais:
        return list(individuais)
    perfil_norm = perfil or 'Vendedor'
    return [r for r in ctx.get('regras_perfil', []) if (r.perfil or '') == perfil_norm]


def encontrar_faixa_regra(regras, qtd_vendas):
    for r in sorted(regras, key=lambda x: _safe_min_max_regra(x)[0], reverse=True):
        min_v, max_v = _safe_min_max_regra(r)
        if min_v <= qtd_vendas <= max_v:
            return r
    return None


def indice_faixa_comissao(ctx, usuario_id, perfil, qtd_instaladas):
    """
    Retorna índice da faixa (0 = 1ª faixa) ou -1 se abaixo da 1ª faixa.
    Mesma lógica de resolução da folha (individual → perfil).
    """
    regras = _regras_aplicaveis_vendedor(ctx, usuario_id, perfil)
    if not regras:
        return -1
    ordenadas = sorted(regras, key=lambda x: _safe_min_max_regra(x)[0])
    qtd = int(qtd_instaladas or 0)
    primeira_min, _ = _safe_min_max_regra(ordenadas[0])
    if qtd < primeira_min:
        return -1
    faixa = encontrar_faixa_regra(regras, qtd)
    if not faixa:
        return -1
    for i, r in enumerate(ordenadas):
        if r.pk == faixa.pk:
            return i
    return -1


def cores_linha_mensal_faixa(ctx, usuario_id, perfil, instaladas):
    idx = indice_faixa_comissao(ctx, usuario_id, perfil, instaladas)
    return cores_linha_por_indice_faixa(idx)


def classe_css_faixa_indice(indice_faixa):
    """Classes CSS do painel (aba mensal)."""
    if indice_faixa is None or indice_faixa < 0:
        return 'row-perf-below-faixa'
    n = min(int(indice_faixa) + 1, 6)
    return f'row-perf-faixa-{n}'


def cor_linha_item_whatsapp(item, tipo, ctx=None):
    """
    (bg_rgb, text_rgb) para imagem WhatsApp.
    item: dict com total, instaladas, usuario_id, perfil_comissao.
    ctx: dias_decorridos, ctx_faixas (opcional, carrega se mensal e ausente).
    """
    ctx = ctx or {}
    tipo = (tipo or 'HOJE').upper()
    if tipo == 'HOJE':
        return cores_linha_performance(item.get('total') or 0)
    if tipo == 'SEMANAL':
        return cores_linha_semanal(
            item.get('total') or 0,
            ctx.get('dias_decorridos', 1),
        )
    if tipo == 'MENSAL':
        faixas_ctx = ctx.get('ctx_faixas')
        if faixas_ctx is None:
            faixas_ctx = carregar_contexto_faixas_comissao()
        return cores_linha_mensal_faixa(
            faixas_ctx,
            item.get('usuario_id'),
            item.get('perfil_comissao'),
            item.get('instaladas') or 0,
        )
    return cores_linha_performance(item.get('total') or 0)


def calcular_dvu(volume: int | float, peso_realizado: float) -> float:
    """Média ponderada por dia útil fiscal (2 casas decimais)."""
    if not peso_realizado or float(peso_realizado) == 0:
        return 0.0
    return round(float(volume) / float(peso_realizado), 2)


def tipo_peso_gestao(tipo_metrica: str) -> TipoPesoFiscal:
    """Mapeia gestao_tipo para peso fiscal (VB ou GR)."""
    return 'GR' if (tipo_metrica or '').strip().upper() == 'INSTALADA' else 'VB'


def calcular_pct_representatividade(volume: int | float, total_geral: int | float) -> float:
    """Participação percentual do vendedor no volume total do período."""
    if not total_geral or float(total_geral) == 0:
        return 0.0
    return round((float(volume) / float(total_geral)) * 100.0, 2)


def limite_peso_mes(mes_inicio: date, mes_fim: date, hoje_ref: date) -> date:
    """Mês em andamento usa dias decorridos; mês fechado usa o mês inteiro."""
    if mes_inicio <= hoje_ref <= mes_fim:
        return hoje_ref
    return mes_fim


def ordenar_lista_performance(lista, key_cluster='cluster', key_nome='nome'):
    """Ordena por cluster (1→2→3) e, dentro do cluster, por nome."""
    return sorted(
        lista,
        key=lambda x: (
            ordem_cluster_performance(x.get(key_cluster)),
            str(x.get(key_nome, '')).upper(),
        ),
    )
