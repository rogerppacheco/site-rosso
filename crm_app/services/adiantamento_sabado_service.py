"""Quitação de adiantamento sábado ao instalar (evita pagamento duplicado na folha)."""
from __future__ import annotations

import logging
from datetime import datetime, time

from django.utils import timezone

logger = logging.getLogger(__name__)


def _nome_status(status_esteira) -> str:
    return (status_esteira.nome if status_esteira else '') or ''


def status_esteira_eh_instalada(status_esteira) -> bool:
    return 'INSTALADA' in _nome_status(status_esteira).upper()


def status_esteira_eh_cancelada(status_esteira) -> bool:
    return 'CANCEL' in _nome_status(status_esteira).upper()


def status_esteira_eh_agendado_ou_pendenciada(status_esteira) -> bool:
    nome = _nome_status(status_esteira).upper()
    if status_esteira_eh_instalada(status_esteira):
        return False
    return 'AGENDADO' in nome or 'PENDEN' in nome


def comissao_ja_adiantada_venda(venda) -> bool:
    """
    Venda não deve entrar em QTD A PAGAR na folha.
    Reemissão instalada sem adiantamento sábado próprio paga normalmente.
    Estorno já aplicado na folha e depois instalada → paga comissão normal.
    """
    if (
        getattr(venda, 'reemissao', False)
        and not getattr(venda, 'adiantamento_sabado_marcado', False)
        and not getattr(venda, 'antecipacao_comissao', False)
    ):
        return False
    if (
        getattr(venda, 'flag_desc_adiantamento_sabado', False)
        and status_esteira_eh_instalada(venda.status_esteira)
        and not getattr(venda, 'adiantamento_sabado_quitado_em', None)
    ):
        return False
    if getattr(venda, 'antecipacao_comissao', False):
        return True
    if getattr(venda, 'adiantamento_sabado_quitado_em', None):
        return True
    return False


def venda_elegivel_estorno_adiantamento_sabado(venda) -> bool:
    """Adiantamento sábado vira estorno quando a venda não instalou (uma vez só, flag_desc=False)."""
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if getattr(venda, 'flag_desc_adiantamento_sabado', False):
        return False
    if getattr(venda, 'adiantamento_sabado_quitado_em', None):
        return False
    val = valor_pago_adiantamento_sabado_venda(venda)
    if not val or float(val) <= 0:
        return False
    if status_esteira_eh_instalada(venda.status_esteira):
        return False
    if (
        status_esteira_eh_cancelada(venda.status_esteira)
        or status_esteira_eh_agendado_ou_pendenciada(venda.status_esteira)
    ):
        return True
    return False


def _data_abertura_os_estorno(venda):
    """Data de abertura da O.S. para estorno sábado (sem fallback — exige correção se ausente)."""
    dt = getattr(venda, 'data_abertura', None)
    if not dt:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.date() if hasattr(dt, 'date') else dt


def _status_permite_estorno_sabado(status_esteira) -> bool:
    return (
        status_esteira_eh_cancelada(status_esteira)
        or status_esteira_eh_agendado_ou_pendenciada(status_esteira)
    )


def venda_entra_estorno_adiantamento_sabado_mes(venda, data_inicio, data_fim) -> bool:
    """
    Mês M da folha (safra = abertura da O.S.):
    - CANCELADA ou AGENDADO/PENDENCIADA: data_abertura da O.S. em M.
    """
    if not venda_elegivel_estorno_adiantamento_sabado(venda):
        return False
    if not _status_permite_estorno_sabado(venda.status_esteira):
        return False

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    dab = _data_abertura_os_estorno(venda)
    if not dab:
        return False
    return di <= dab < df


def coletar_vendas_adiantamento_sabado_sem_data_abertura(
    consultor,
    data_inicio,
    data_fim,
) -> list[dict]:
    """
    Vendas elegíveis a estorno sábado (cancelada/agendada/pendenciada) sem data_abertura.
    Não entram na folha até correção manual da data de abertura da O.S.
    """
    from crm_app.models import Venda

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    if not di or not df:
        return []

    vendas = (
        Venda.objects.filter(
            vendedor=consultor,
            ativo=True,
            adiantamento_sabado_marcado=True,
            flag_desc_adiantamento_sabado=False,
            adiantamento_sabado_quitado_em__isnull=True,
            data_abertura__isnull=True,
        )
        .exclude(adiantamento_sabado_valor__isnull=True)
        .exclude(adiantamento_sabado_valor=0)
        .select_related('status_esteira', 'cliente')
    )

    alertas: list[dict] = []
    for venda in vendas:
        if not venda_elegivel_estorno_adiantamento_sabado(venda):
            continue
        if not _status_permite_estorno_sabado(venda.status_esteira):
            continue
        alertas.append(
            {
                'tipo': 'adiantamento_sabado_sem_data_abertura',
                'venda_id': venda.id,
                'os': venda.ordem_servico or '',
                'nome': (
                    (venda.cliente.nome_razao_social or '')[:80]
                    if getattr(venda, 'cliente', None)
                    else ''
                ),
                'situacao': _nome_status(venda.status_esteira),
                'mensagem': (
                    'Venda com adiantamento sábado sem data de abertura da O.S. '
                    '— corrija no cadastro para o estorno entrar na folha.'
                ),
            }
        )
    return alertas


def motivo_estorno_adiantamento_sabado(venda) -> str:
    if status_esteira_eh_cancelada(venda.status_esteira):
        return 'Desconto adiantamento sábado (cancelado)'
    return 'Desconto adiantamento sábado (não instalado)'


def calcular_descontos_adiantamento_sabado_folha(consultor, data_inicio, data_fim):
    """
    Estorno automático na folha do mês da abertura da O.S. (safra):
    - CANCELADA, AGENDADO ou PENDENCIADA com adiantamento sábado, sem instalar;
    - flag_desc evita repetir; valor = pago no sábado.
    """
    from crm_app.models import Venda

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    if not di or not df:
        return []

    vendas = (
        Venda.objects.filter(
            vendedor=consultor,
            ativo=True,
            adiantamento_sabado_marcado=True,
            flag_desc_adiantamento_sabado=False,
            adiantamento_sabado_quitado_em__isnull=True,
        )
        .exclude(adiantamento_sabado_valor__isnull=True)
        .exclude(adiantamento_sabado_valor=0)
        .select_related('status_esteira')
    )

    descontos = []
    for v in vendas:
        if not venda_entra_estorno_adiantamento_sabado_mes(v, di, df):
            continue
        val = valor_pago_adiantamento_sabado_venda(v)
        if val <= 0:
            continue
        descontos.append({
            'venda_id': v.id,
            'valor': val,
            'motivo': motivo_estorno_adiantamento_sabado(v),
        })
    return descontos


def get_vendas_ids_desconto_adiantamento_sabado_mes(ano, mes):
    """IDs com estorno na folha do mês — usado ao fechar para marcar flag_desc (uma vez só)."""
    from crm_app.models import Venda

    data_inicio = datetime(ano, mes, 1)
    data_fim = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)
    di = data_inicio.date()
    df = data_fim.date()

    ids = []
    qs = (
        Venda.objects.filter(
            ativo=True,
            adiantamento_sabado_marcado=True,
            flag_desc_adiantamento_sabado=False,
            adiantamento_sabado_quitado_em__isnull=True,
            vendedor_id__isnull=False,
        )
        .exclude(adiantamento_sabado_valor__isnull=True)
        .exclude(adiantamento_sabado_valor=0)
        .select_related('status_esteira')
    )
    for v in qs:
        if venda_entra_estorno_adiantamento_sabado_mes(v, di, df):
            ids.append(v.id)
    return ids


def quitado_em_a_partir_data_instalacao(venda):
    """Timestamp de quitação alinhado à data de instalação (retrofit / consistência)."""
    dt = getattr(venda, 'data_instalacao', None)
    if not dt:
        return timezone.now()
    if hasattr(dt, 'date'):
        dt = dt.date()
    naive = datetime.combine(dt, time(18, 0, 0))
    tz = timezone.get_current_timezone()
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, tz)
    return naive


def quitar_adiantamento_sabado_na_instalacao(
    venda,
    status_esteira_antes=None,
    *,
    quitado_em=None,
) -> bool:
    """
    Ao instalar venda com adiantamento sábado: marca antecipação e quitação sem novo lançamento.
    Se já houve estorno na folha (flag_desc), não quita — comissão paga normal na instalação.
    """
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    if status_esteira_antes is not None:
        if status_esteira_eh_instalada(status_esteira_antes):
            return False
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if getattr(venda, 'flag_desc_adiantamento_sabado', False):
        return False

    ts = quitado_em or venda.adiantamento_sabado_quitado_em or quitado_em_a_partir_data_instalacao(venda)

    from crm_app.models import Venda

    # Já quitada mas antecipacao_comissao foi zerada (ex.: desmarcar/remarcar na esteira).
    if venda.adiantamento_sabado_quitado_em and not venda.antecipacao_comissao:
        updated = Venda.objects.filter(
            pk=venda.pk,
            adiantamento_sabado_marcado=True,
            antecipacao_comissao=False,
        ).update(antecipacao_comissao=True)
        if updated:
            venda.antecipacao_comissao = True
            logger.info(
                'Antecipação resincronizada após quitação sábado — venda #%s',
                venda.pk,
            )
        return bool(updated)

    if venda.adiantamento_sabado_quitado_em:
        return False

    updated = Venda.objects.filter(
        pk=venda.pk,
        adiantamento_sabado_marcado=True,
        adiantamento_sabado_quitado_em__isnull=True,
    ).update(
        antecipacao_comissao=True,
        adiantamento_sabado_quitado_em=ts,
    )
    if updated:
        venda.antecipacao_comissao = True
        venda.adiantamento_sabado_quitado_em = ts
        logger.info(
            'Adiantamento sábado quitado na instalação — venda #%s (quitado_em=%s)',
            venda.pk,
            ts,
        )
    return bool(updated)


def sincronizar_antecipacao_quitado_sabado(venda) -> bool:
    """Quitado_em preenchido mas antecipacao_comissao=False — repara folha sem remarcar sábado."""
    if not getattr(venda, 'adiantamento_sabado_quitado_em', None):
        return False
    if getattr(venda, 'antecipacao_comissao', False):
        return False
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    from crm_app.models import Venda

    updated = Venda.objects.filter(pk=venda.pk, antecipacao_comissao=False).update(
        antecipacao_comissao=True,
    )
    if updated:
        venda.antecipacao_comissao = True
        logger.info('Antecipação resincronizada (quitado_em) — venda #%s', venda.pk)
    return bool(updated)


def garantir_quitacao_adiantamento_sabado_instalada(venda) -> bool:
    """
    Venda INSTALADA com adiantamento sábado marcado: garante antecipacao_comissao + quitado_em.
    Não aplica se já houve estorno na folha (instalação posterior paga comissão normal).
    """
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if getattr(venda, 'flag_desc_adiantamento_sabado', False):
        return False
    if venda.antecipacao_comissao and venda.adiantamento_sabado_quitado_em:
        return False

    ts = venda.adiantamento_sabado_quitado_em or quitado_em_a_partir_data_instalacao(venda)
    from crm_app.models import Venda

    updated = Venda.objects.filter(pk=venda.pk).update(
        antecipacao_comissao=True,
        adiantamento_sabado_quitado_em=ts,
    )
    if updated:
        venda.antecipacao_comissao = True
        venda.adiantamento_sabado_quitado_em = ts
        logger.info(
            'Quitação sábado garantida em venda instalada — #%s (quitado_em=%s)',
            venda.pk,
            ts,
        )
    return bool(updated)


def valor_pago_adiantamento_sabado_venda(
    venda,
    valores_lancamento: dict[int, float] | None = None,
) -> float:
    """
    Valor efetivamente pago no sábado (não inclui complemento de faixa da folha).
    Prioridade: adiantamento_sabado_valor_pago → lançamento financeiro → adiantamento_sabado_valor.
    """
    vp = getattr(venda, 'adiantamento_sabado_valor_pago', None)
    if vp is not None and float(vp) > 0:
        return float(vp)
    vid = getattr(venda, 'pk', None) or getattr(venda, 'id', None)
    if valores_lancamento and vid is not None:
        val_lanc = valores_lancamento.get(int(vid))
        if val_lanc is not None and float(val_lanc) > 0:
            return float(val_lanc)
    val = getattr(venda, 'adiantamento_sabado_valor', None)
    if val is not None and float(val) > 0:
        return float(val)
    return 0.0


def carregar_valores_pago_sabado_lancamentos(
    vendedor_id: int | None = None,
) -> dict[int, float]:
    """Mapa venda_id → valor pago conforme metadados dos lançamentos de sábado."""
    from crm_app.models import LancamentoFinanceiro

    qs = LancamentoFinanceiro.objects.filter(tipo='ADIANTAMENTO_COMISSAO')
    if vendedor_id:
        qs = qs.filter(usuario_id=vendedor_id)
    mapa: dict[int, float] = {}
    for lanc in qs.only('metadados', 'usuario_id'):
        meta = lanc.metadados if isinstance(lanc.metadados, dict) else {}
        if meta.get('origem') != 'esteira_sabado_agendados':
            continue
        for vid, val in (meta.get('valores_por_venda_id') or {}).items():
            try:
                mapa[int(vid)] = float(val)
            except (TypeError, ValueError):
                continue
    return mapa


def chave_comissao_venda(venda, cidades_especiais_cache=None) -> str | None:
    """Chave de exibição na folha (respeitando MEI → PAP e cidade especial)."""
    from crm_app.comissao_folha_service import plano_tipo_to_chave
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

    plano_nome = venda.plano.nome if getattr(venda, 'plano', None) else ''
    return plano_tipo_to_chave(
        plano_nome,
        tipo_cliente_comissao(venda),
        venda=venda,
        cidades_especiais_cache=cidades_especiais_cache,
    )


def valor_alvo_adiantamento_sabado_folha(
    venda,
    *,
    faixa_regra,
    config,
    usar_manual: bool,
    matriz_cache=None,
    cidades_especiais_cache=None,
) -> float | None:
    """
    Valor-alvo do adiantamento sábado para venda instalada na folha do mês.
    Usa Regras por Faixa (COMISSÃO) ou valores manuais da config do vendedor.
    """
    from crm_app.comissao_folha_service import resolver_valor_comissao_venda
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

    chave = chave_comissao_venda(venda, cidades_especiais_cache=cidades_especiais_cache)
    if not chave:
        return None
    return resolver_valor_comissao_venda(
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


def calcular_complemento_adiantamento_sabado_folha(
    vendas_instaladas,
    *,
    faixa_regra_total,
    config,
    usar_manual: bool,
    valores_lancamento: dict[int, float] | None = None,
    matriz_cache=None,
    cidades_especiais_cache=None,
) -> dict:
    """
    Complemento de faixa para vendas instaladas com adiantamento sábado.
    complemento = valor_alvo_faixa − valor_pago_sábado (pode ser negativo na rebaixa).
    Não persiste alterações — entra no líquido da folha e na exibição.
    """
    from crm_app.services.cnpj_mei_service import classificacao_mei_venda, tipo_cliente_comissao

    por_venda: dict[int, dict] = {}
    por_plano: dict[str, dict] = {}
    detalhes: list[dict] = []
    total_complemento = 0.0
    total_pago = 0.0
    total_alvo = 0.0
    qtd_complemento = 0
    faixa_nome = getattr(faixa_regra_total, 'faixa_nome', None) if faixa_regra_total else None

    for venda in vendas_instaladas:
        if not getattr(venda, 'adiantamento_sabado_marcado', False):
            continue
        if getattr(venda, 'flag_desc_adiantamento_sabado', False):
            continue

        pago = valor_pago_adiantamento_sabado_venda(venda, valores_lancamento)
        if pago <= 0:
            continue

        alvo = valor_alvo_adiantamento_sabado_folha(
            venda,
            faixa_regra=faixa_regra_total,
            config=config,
            usar_manual=usar_manual,
            matriz_cache=matriz_cache,
            cidades_especiais_cache=cidades_especiais_cache,
        )
        if alvo is None:
            continue

        complemento = round(float(alvo) - pago, 2)
        alvo_r = round(float(alvo), 2)
        pago_r = round(pago, 2)

        plano_nome = venda.plano.nome if getattr(venda, 'plano', None) else ''
        chave = chave_comissao_venda(venda, cidades_especiais_cache=cidades_especiais_cache) or ''
        mei = classificacao_mei_venda(venda)
        tipo_cli = tipo_cliente_comissao(venda)

        por_venda[venda.pk] = {
            'pago': pago_r,
            'alvo': alvo_r,
            'complemento': complemento,
            'chave': chave,
            'classificacao_mei': mei,
            'tipo_cliente': tipo_cli,
        }
        if complemento != 0:
            qtd_complemento += 1
            detalhes.append(
                {
                    'venda_id': venda.pk,
                    'os': getattr(venda, 'ordem_servico', None) or '',
                    'plano': plano_nome,
                    'chave': chave,
                    'classificacao_mei': mei or '-',
                    'tipo_cliente': tipo_cli,
                    'pago': pago_r,
                    'alvo': alvo_r,
                    'complemento': complemento,
                    'faixa_nome': faixa_nome,
                }
            )

        total_pago += pago_r
        total_alvo += alvo_r
        total_complemento += complemento

        if chave:
            slot = por_plano.setdefault(
                chave,
                {'qtd': 0, 'pago': 0.0, 'complemento': 0.0, 'alvo': 0.0},
            )
            slot['qtd'] += 1
            slot['pago'] += pago_r
            slot['complemento'] += complemento
            slot['alvo'] += alvo_r

    return {
        'total_complemento': round(total_complemento, 2),
        'total_pago': round(total_pago, 2),
        'total_alvo': round(total_alvo, 2),
        'quantidade_complemento': qtd_complemento,
        'por_venda': por_venda,
        'por_plano': por_plano,
        'detalhes': detalhes,
        'faixa_nome': faixa_nome,
    }


def quitar_adiantamento_sabado_pos_bulk(vendas) -> int:
    """
    Após bulk_update (OSAB etc.) que altera status_esteira sem disparar signals.
    status_esteira_antes omitido: só quita se ainda pendente (adiantamento_sabado_quitado_em vazio).
    """
    count = 0
    for venda in vendas:
        try:
            if quitar_adiantamento_sabado_na_instalacao(venda, status_esteira_antes=None):
                count += 1
        except Exception:
            logger.exception(
                'Erro ao quitar adiantamento sábado pós-bulk — venda #%s',
                getattr(venda, 'pk', '?'),
            )
    return count
