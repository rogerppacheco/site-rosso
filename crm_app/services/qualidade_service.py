"""Serviço do módulo Qualidade (FPD + bônus M-10).

Centraliza permissões, consultas por lente (vencimento | instalação),
sincronização de faltantes, órfãos FPD e envio de cobrança (WhatsApp/e-mail).
Views devem permanecer enxutas e delegar a este serviço.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, timedelta
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import CharField, Count, F, Func, Q, QuerySet, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from crm_app.fpd_status_mapping import (
    INDICADOR_PARA_NUMERO_FATURA,
    NUMERO_FATURA_PARA_INDICADOR,
)
from crm_app.models import (
    Cliente,
    ContratoM10,
    FaturaM10,
    ImportacaoFPD,
    SafraM10,
    StatusCRM,
    Venda,
)
from crm_app.utils import is_member
from crm_app.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


class _StripNonDigits(Func):
    """PostgreSQL: normaliza telefone removendo tudo que não for dígito."""

    function = 'REGEXP_REPLACE'
    template = "%(function)s(%(expressions)s, '[^0-9]', '', 'g')"
    output_field = CharField()


# PAGO + OUTROS (Cancelada/Zerada/FECHADA): fechadas na visão FPD — entram em "Pagas"
# sem alterar o status exibido (mantém OUTROS para rastrear cancelamento).
STATUS_FATURA_FECHADA: frozenset[str] = frozenset({'PAGO', 'OUTROS'})
STATUS_FATURA_ABERTA_PROMESSA: frozenset[str] = frozenset({'NAO_PAGO', 'ATRASADO', 'AGUARDANDO'})

# Safra de vencimento fecha o tratamento no fim do mês + 2 (ex.: jun/26 → até ago/26).
MESES_OFFSET_LIMITE_VENCIMENTO = 2
# Meta operacional de FPD (inadimplência da 1ª fatura) no mês.
META_FPD_PCT = 11.0
# Atraso da 1ª fatura a partir do qual o FPD da empresa já está consolidado.
ATRASO_LIMITE_FPD_DIAS = 60
# Horário local (TIME_ZONE) do job de templates D−5 / D+5 / recorrente.
HORARIO_JOB_COBRANCA = '09:00'
FILA_ATRASADOS = 'atrasados'
FILA_ATRASADOS_LT60 = 'atrasados_lt60'
FILA_ATRASADOS_GTE60 = 'atrasados_gte60'


def _fatura_esta_fechada(status: Optional[str]) -> bool:
    """True se a fatura conta como paga/fechada operacionalmente."""
    return (status or '').upper() in STATUS_FATURA_FECHADA


# ---------------------------------------------------------------------------
# HistoricoEnvioQualidade (quando existir no models.py):
#   contrato = FK(ContratoM10, related_name='historico_envios_qualidade')
#   fatura = FK(FaturaM10, null=True, blank=True)
#   canal = CharField choices WHATSAPP | EMAIL
#   destinatario = CharField
#   mensagem = TextField
#   enviado_por = FK(Usuario, null=True)
#   sucesso = BooleanField(default=True)
#   erro = TextField(null=True, blank=True)
#   criado_em = DateTimeField(auto_now_add=True)
# ---------------------------------------------------------------------------
try:
    from crm_app.models import HistoricoEnvioQualidade  # type: ignore[attr-defined]
except ImportError:
    HistoricoEnvioQualidade = None  # type: ignore[misc, assignment]

GRUPOS_QUALIDADE: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Qualidade',
    'Auditoria',
]
GRUPOS_VALOR_BONUS: list[str] = ['Diretoria', 'Admin']

VALOR_BONUS_M10: int = 150

LENTE_VENCIMENTO = 'vencimento'
LENTE_INSTALACAO = 'instalacao'

_MESES_PT: dict[int, str] = {
    1: 'Janeiro',
    2: 'Fevereiro',
    3: 'Março',
    4: 'Abril',
    5: 'Maio',
    6: 'Junho',
    7: 'Julho',
    8: 'Agosto',
    9: 'Setembro',
    10: 'Outubro',
    11: 'Novembro',
    12: 'Dezembro',
}


def pode_acessar_qualidade(user: Any) -> bool:
    """True se o usuário pertence a algum grupo autorizado no módulo Qualidade."""
    return is_member(user, GRUPOS_QUALIDADE)


def pode_acessar_fpd_dashboard(user: Any) -> bool:
    """Dashboard FPD (inclui Gerente de Contas — somente leitura)."""
    from crm_app.perfis_acesso import GRUPOS_FPD_DASHBOARD

    return is_member(user, GRUPOS_FPD_DASHBOARD)


def pode_ver_valor_bonus(user: Any) -> bool:
    """Valor R$ do bônus M-10 só para Diretoria e Admin (padrão já usado no M-10)."""
    return is_member(user, GRUPOS_VALOR_BONUS)


def mes_range(yyyy_mm: str) -> tuple[date, date]:
    """Converte YYYY-MM em (início inclusivo, fim exclusivo) do mês."""
    if not yyyy_mm or len(yyyy_mm) != 7 or yyyy_mm[4] != '-':
        raise ValueError(f'Formato de mês inválido: {yyyy_mm!r}. Use YYYY-MM.')
    ano, mes = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    if mes < 1 or mes > 12:
        raise ValueError(f'Mês inválido: {yyyy_mm!r}.')
    inicio = date(ano, mes, 1)
    fim = inicio + relativedelta(months=1)
    return inicio, fim


def _label_mes(yyyy_mm: str) -> str:
    ano, mes = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    return f'{_MESES_PT.get(mes, f"{mes:02d}")}/{ano}'


def _saudacao_periodo() -> str:
    hora = timezone.localtime().hour
    return 'bom dia' if hora < 12 else 'boa tarde'


def _contrato_tem_campo(nome: str) -> bool:
    return any(f.name == nome for f in ContratoM10._meta.get_fields())


def _eh_orfao(contrato: ContratoM10) -> bool:
    if _contrato_tem_campo('orfao'):
        return bool(getattr(contrato, 'orfao', False))
    obs = (contrato.observacao or '').lower()
    return 'órfão' in obs or 'orfao' in obs


def pode_tratar_contrato(contrato: ContratoM10) -> bool:
    """Cobrança só após vínculo: órfão ou sem CPF bloqueiam tratamento."""
    if _eh_orfao(contrato):
        return False
    cpf = (contrato.cpf_cliente or '').strip()
    return bool(cpf)


def _recalcular_totais_safra(safra_str: str) -> None:
    """Recalcula totais da SafraM10 (instalados, ativos, elegíveis, valor bônus).

    Mesma regra de ``_recalcular_totais_safra_m10`` nas views: elegível =
    ATIVO + sem downgrade + todas as faturas cadastradas pagas
    (fallback FPD paga quando não há faturas).
    """
    try:
        data_inicio, data_fim = mes_range(safra_str)
    except ValueError:
        return

    total_instalados = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).count()
    total_ativos = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
        status_contrato='ATIVO',
    ).count()

    contratos_safra = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).annotate(
        total_faturas=Count('faturas', distinct=True),
        faturas_pagas=Count(
            'faturas',
            filter=Q(faturas__status__in=STATUS_FATURA_FECHADA),
            distinct=True,
        ),
    )
    elegiveis = 0
    for c in contratos_safra:
        total_f = c.total_faturas or 0
        pagas = c.faturas_pagas or 0
        if total_f == 0 and c.status_fatura_fpd and str(c.status_fatura_fpd).lower().startswith('paga'):
            total_f, pagas = 1, 1
        if (
            c.status_contrato == 'ATIVO'
            and not c.teve_downgrade
            and total_f > 0
            and pagas == total_f
        ):
            elegiveis += 1

    SafraM10.objects.filter(mes_referencia=data_inicio).update(
        total_instalados=total_instalados,
        total_ativos=total_ativos,
        total_elegivel_bonus=elegiveis,
        valor_bonus_total=elegiveis * VALOR_BONUS_M10,
    )


def _contrato_elegivel_dinamico(contrato: ContratoM10) -> bool:
    total_f = getattr(contrato, 'total_faturas', None)
    pagas = getattr(contrato, 'faturas_pagas', None)
    if total_f is None:
        total_f = contrato.faturas.count()
    if pagas is None:
        pagas = contrato.faturas.filter(status__in=STATUS_FATURA_FECHADA).count()
    if total_f == 0 and contrato.status_fatura_fpd and str(contrato.status_fatura_fpd).lower().startswith('paga'):
        total_f, pagas = 1, 1
    return (
        contrato.status_contrato == 'ATIVO'
        and not contrato.teve_downgrade
        and total_f > 0
        and pagas == total_f
    )


def _corte_safra_instalacao_tratavel() -> date:
    """Primeiro dia do mês a partir do qual a safra de instalação ainda é tratável.

    Regra: a safra permanece em tratamento enquanto não completou 10 meses
    desde o mês de instalação (ciclo das 10 faturas). Ex.: em jul/2026,
    entram safras com instalação >= set/2025.
    """
    hoje = timezone.localdate()
    return (hoje.replace(day=1) - relativedelta(months=9))


def mes_limite_tratamento_vencimento(hoje: Optional[date] = None) -> str:
    """Safra de vencimento cujo prazo de tratamento fecha no fim do mês corrente.

    Ex.: em ago/2026 → ``2026-06`` (junho fecha até o fim de agosto);
    em set/2026 → ``2026-07`` (julho fecha até o fim de setembro).
    """
    ref = (hoje or timezone.localdate()).replace(day=1)
    alvo = ref - relativedelta(months=MESES_OFFSET_LIMITE_VENCIMENTO)
    return alvo.strftime('%Y-%m')


def _resolver_mes_padrao(
    periodos: list[dict[str, Any]],
    mes_alvo: Optional[str],
) -> str:
    """Escolhe o mês inicial: alvo se existir; senão o mais próximo ≤ alvo; senão o mais recente."""
    if not periodos:
        return ''
    meses = [str(p.get('mes') or '') for p in periodos if p.get('mes')]
    if not meses:
        return ''
    if mes_alvo and mes_alvo in meses:
        return mes_alvo
    if mes_alvo:
        anteriores = [m for m in meses if m <= mes_alvo]
        if anteriores:
            return max(anteriores)
    return meses[0]


def faltam_pagamentos_meta_fpd(
    atrasados: int,
    abertos: int,
    total: int,
    meta_pct: float = META_FPD_PCT,
) -> int:
    """Quantos pagamentos (saída de atrasado/aberto) faltam para FPD ≤ meta.

    FPD = (atrasados + abertos) / total. Mantém o denominador (total do mês).
    """
    if total <= 0 or meta_pct < 0:
        return 0
    inad = max(0, int(atrasados) + int(abertos))
    max_inad = int(total * (float(meta_pct) / 100.0))  # floor para positivos
    return max(0, inad - max_inad)


def listar_periodos(lente: str) -> list[dict[str, Any]]:
    """Lista meses disponíveis na lente, ordenados do mais recente ao mais antigo.

    - ``vencimento``: meses distintos de ``data_vencimento`` da fatura 1.
    - ``instalacao``: só safras que ainda não completaram 10 meses (tratáveis).
    """
    lente_norm = (lente or LENTE_VENCIMENTO).strip().lower()
    periodos: dict[str, dict[str, Any]] = {}
    mes_limite = (
        mes_limite_tratamento_vencimento()
        if lente_norm == LENTE_VENCIMENTO
        else ''
    )

    if lente_norm == LENTE_INSTALACAO:
        corte = _corte_safra_instalacao_tratavel()
        for safra in SafraM10.objects.filter(mes_referencia__gte=corte).order_by('-mes_referencia'):
            mes_key = safra.mes_referencia.strftime('%Y-%m')
            periodos[mes_key] = {
                'mes': mes_key,
                'label': _label_mes(mes_key),
                'total': safra.total_instalados or 0,
                'ativos': safra.total_ativos or 0,
                'elegiveis': safra.total_elegivel_bonus or 0,
                'tratavel': True,
                'no_limite': False,
            }

        qs = (
            ContratoM10.objects.filter(data_instalacao__gte=corte)
            .annotate(mes_ref=TruncMonth('data_instalacao'))
            .values('mes_ref')
            .annotate(
                total=Count('id'),
                ativos=Count('id', filter=Q(status_contrato='ATIVO')),
                elegiveis=Count('id', filter=Q(elegivel_bonus=True)),
            )
        )
        for row in qs:
            mes_ref: date | None = row['mes_ref']
            if not mes_ref:
                continue
            mes_key = mes_ref.strftime('%Y-%m')
            periodos[mes_key] = {
                'mes': mes_key,
                'label': _label_mes(mes_key),
                'total': row['total'],
                'ativos': row['ativos'],
                'elegiveis': row['elegiveis'],
                'tratavel': True,
                'no_limite': False,
            }
    else:
        qs = (
            FaturaM10.objects.filter(numero_fatura=1)
            .exclude(data_vencimento__isnull=True)
            .annotate(mes_ref=TruncMonth('data_vencimento'))
            .values('mes_ref')
            .annotate(
                total=Count('id'),
                pagas=Count('id', filter=Q(status__in=STATUS_FATURA_FECHADA)),
                abertas=Count('id', filter=~Q(status__in=STATUS_FATURA_FECHADA)),
            )
        )
        for row in qs:
            mes_ref = row['mes_ref']
            if not mes_ref:
                continue
            mes_key = mes_ref.strftime('%Y-%m')
            periodos[mes_key] = {
                'mes': mes_key,
                'label': _label_mes(mes_key),
                'total': row['total'],
                'abertas': row['abertas'],
                'pagas': row['pagas'],
                'no_limite': mes_key == mes_limite,
            }

    return sorted(periodos.values(), key=lambda p: p['mes'], reverse=True)


def payload_periodos_qualidade(lente: str) -> dict[str, Any]:
    """Resposta da API de períodos, com mês padrão (safra no limite de tratamento)."""
    lente_norm = (lente or LENTE_VENCIMENTO).strip().lower()
    periodos = listar_periodos(lente_norm)
    mes_limite = (
        mes_limite_tratamento_vencimento()
        if lente_norm == LENTE_VENCIMENTO
        else ''
    )
    mes_padrao = _resolver_mes_padrao(periodos, mes_limite or None)
    return {
        'lente': lente_norm,
        'periodos': periodos,
        'mes_padrao': mes_padrao,
        'mes_limite_tratamento': mes_limite,
        'meta_fpd_pct': META_FPD_PCT,
    }


def _aplicar_filtros_contratos(
    queryset: QuerySet[ContratoM10],
    filtros: dict[str, Any],
) -> QuerySet[ContratoM10]:
    vendedor = filtros.get('vendedor')
    if vendedor not in (None, '', '0', 0, 'todos'):
        try:
            queryset = queryset.filter(vendedor_id=int(vendedor))
        except (TypeError, ValueError):
            pass

    status = filtros.get('status') or filtros.get('status_contrato')
    if status:
        queryset = queryset.filter(status_contrato=status)

    elegivel = filtros.get('elegivel')
    if elegivel is not None and elegivel != '':
        if isinstance(elegivel, str):
            queryset = queryset.filter(elegivel_bonus=(elegivel.lower() in ('true', '1', 'sim')))
        else:
            queryset = queryset.filter(elegivel_bonus=bool(elegivel))

    orfao = filtros.get('orfao')
    if orfao is not None and orfao != '' and _contrato_tem_campo('orfao'):
        if isinstance(orfao, str):
            queryset = queryset.filter(orfao=(orfao.lower() in ('true', '1', 'sim')))
        else:
            queryset = queryset.filter(orfao=bool(orfao))

    status_tratamento_id = filtros.get('status_tratamento_id') or filtros.get('status_tratamento')
    if status_tratamento_id not in (None, ''):
        if str(status_tratamento_id).lower() in ('null', 'vazio', 'sem'):
            queryset = queryset.filter(status_tratamento__isnull=True)
        elif str(status_tratamento_id).isdigit():
            queryset = queryset.filter(status_tratamento_id=int(status_tratamento_id))

    status_fatura1 = filtros.get('status_fatura1')
    if status_fatura1:
        queryset = queryset.filter(
            faturas__numero_fatura=1,
            faturas__status=status_fatura1,
        ).distinct()

    conferencia_fpd = (filtros.get('conferencia_fpd') or '').strip().upper()
    if conferencia_fpd:
        queryset = queryset.filter(
            faturas__numero_fatura=1,
            faturas__conferencia_fpd=conferencia_fpd,
        ).distinct()

    faixa_atraso = (filtros.get('faixa_atraso') or filtros.get('faixa') or '').strip()
    if faixa_atraso:
        queryset = queryset.filter(
            _q_faixa_atraso_fatura1(faixa_atraso, timezone.localdate())
        ).distinct()

    promessa = (filtros.get('promessa') or '').strip().lower()
    if promessa:
        q_prom = _q_promessa_pagamento(promessa, timezone.localdate())
        if q_prom:
            queryset = queryset.filter(q_prom).distinct()

    busca = filtros.get('q') or filtros.get('busca')
    if busca:
        busca_digits = re.sub(r'\D', '', str(busca))
        filtros_busca = (
            Q(numero_contrato__icontains=busca)
            | Q(numero_contrato_definitivo__icontains=busca)
            | Q(cliente_nome__icontains=busca)
            | Q(ordem_servico__icontains=busca)
        )
        if busca_digits:
            filtros_busca |= Q(cpf_cliente__icontains=busca_digits)
            # Celular 1/2 do cadastro da venda (com ou sem máscara / DDI 55).
            # A busca geral (q com 2+ chars) já varre todas as safras FPD.
            if len(busca_digits) >= 8:
                queryset = queryset.annotate(
                    _tel1_digitos=_StripNonDigits(
                        Coalesce(F('venda__telefone1'), Value(''))
                    ),
                    _tel2_digitos=_StripNonDigits(
                        Coalesce(F('venda__telefone2'), Value(''))
                    ),
                )
                for variante in _variantes_busca_telefone(busca_digits):
                    filtros_busca |= (
                        Q(_tel1_digitos__contains=variante)
                        | Q(_tel2_digitos__contains=variante)
                    )
                if _contrato_tem_campo('telefone'):
                    queryset = queryset.annotate(
                        _tel_contrato_digitos=_StripNonDigits(
                            Coalesce(F('telefone'), Value(''))
                        ),
                    )
                    for variante in _variantes_busca_telefone(busca_digits):
                        filtros_busca |= Q(_tel_contrato_digitos__contains=variante)
        queryset = queryset.filter(filtros_busca)

    return queryset


def _variantes_busca_telefone(busca_digits: str) -> set[str]:
    """Variantes de dígitos para casar telefone digitado com o cadastro."""
    variantes = {
        v for v in _digitos_telefone_variantes(busca_digits) if len(v) >= 8
    }
    for n in (8, 9, 10, 11):
        if len(busca_digits) >= n:
            variantes.add(busca_digits[-n:])
    return variantes


def _q_promessa_pagamento(faixa: str, hoje: date) -> Q:
    """Contratos com fatura em aberto e data de promessa na faixa informada."""
    base = (
        Q(faturas__status__in=STATUS_FATURA_ABERTA_PROMESSA)
        & Q(faturas__data_promessa_pagamento__isnull=False)
    )
    faixa_n = (faixa or '').strip().lower()
    if faixa_n in ('hoje', 'today'):
        return base & Q(faturas__data_promessa_pagamento=hoje)
    if faixa_n in ('atrasada', 'atrasadas', 'vencida'):
        return base & Q(faturas__data_promessa_pagamento__lt=hoje)
    if faixa_n in ('proximos', 'proximas', 'proximos_3'):
        limite = hoje + relativedelta(days=3)
        return (
            base
            & Q(faturas__data_promessa_pagamento__gt=hoje)
            & Q(faturas__data_promessa_pagamento__lte=limite)
        )
    if faixa_n in ('todas', 'todos', 'com_promessa'):
        return base
    return Q()


def contagens_promessas(queryset: QuerySet[ContratoM10], hoje: Optional[date] = None) -> dict[str, int]:
    """Contagens de promessa de pagamento (faturas em aberto) para o lembrete do BO."""
    ref = hoje or timezone.localdate()
    return {
        'hoje': queryset.filter(_q_promessa_pagamento('hoje', ref)).distinct().count(),
        'atrasadas': queryset.filter(_q_promessa_pagamento('atrasada', ref)).distinct().count(),
        'proximos': queryset.filter(_q_promessa_pagamento('proximos', ref)).distinct().count(),
        'todas': queryset.filter(_q_promessa_pagamento('todas', ref)).distinct().count(),
    }


def _promessa_aberta_contrato(
    faturas: list[FaturaM10],
    hoje: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Menor data de promessa entre faturas em aberto do contrato."""
    ref = hoje or timezone.localdate()
    candidatas = [
        f for f in faturas
        if f.data_promessa_pagamento
        and not _fatura_esta_fechada(f.status)
    ]
    if not candidatas:
        return None
    candidatas.sort(key=lambda f: f.data_promessa_pagamento or date.max)
    f = candidatas[0]
    d = f.data_promessa_pagamento
    if d is None:
        return None
    if d < ref:
        faixa = 'atrasada'
    elif d == ref:
        faixa = 'hoje'
    elif d <= ref + relativedelta(days=3):
        faixa = 'proximos'
    else:
        faixa = 'futura'
    return {
        'data': d.isoformat(),
        'faixa': faixa,
        'numero_fatura': f.numero_fatura,
    }


def _q_fatura1_atrasada(hoje: date) -> Q:
    """1ª fatura em débito vencido (visão tratamento / BO).

    OUTROS (ex.: Cancelada) não entra aqui — vai para Pagas/fechadas.
    """
    return Q(faturas__numero_fatura=1) & (
        Q(faturas__status='ATRASADO')
        | (
            Q(faturas__status__in=['NAO_PAGO', 'AGUARDANDO'])
            & Q(faturas__data_vencimento__lt=hoje)
        )
    )


def corte_vencimento_fpd(hoje: Optional[date] = None) -> date:
    """Vencimento nesta data ou antes = atraso ≥ 60 dias (FPD consolidado)."""
    ref = hoje or timezone.localdate()
    return ref - timedelta(days=ATRASO_LIMITE_FPD_DIAS)


def classificar_fila_atraso(dias_atraso: int) -> str:
    """Bucket operacional: recuperável (< 60d) vs FPD consolidado (≥ 60d)."""
    try:
        d = int(dias_atraso or 0)
    except (TypeError, ValueError):
        d = 0
    if d >= ATRASO_LIMITE_FPD_DIAS:
        return FILA_ATRASADOS_GTE60
    return FILA_ATRASADOS_LT60


def _q_fatura1_atrasada_lt60(hoje: date) -> Q:
    """Atrasado com menos de 60 dias — ainda dá para recuperar o FPD."""
    corte = corte_vencimento_fpd(hoje)
    return _q_fatura1_atrasada(hoje) & (
        Q(faturas__data_vencimento__gt=corte)
        | Q(faturas__data_vencimento__isnull=True)
    )


def _q_fatura1_atrasada_gte60(hoje: date) -> Q:
    """Atrasado com 60+ dias — FPD já consolidado para a empresa."""
    corte = corte_vencimento_fpd(hoje)
    return _q_fatura1_atrasada(hoje) & Q(faturas__data_vencimento__lte=corte)


def _q_fatura1_em_aberto(hoje: date) -> Q:
    """1ª fatura em aberto ainda no prazo (visão tratamento / BO)."""
    return (
        Q(faturas__numero_fatura=1)
        & Q(faturas__status__in=['NAO_PAGO', 'AGUARDANDO'])
        & Q(faturas__data_vencimento__gte=hoje)
    )


def _q_fatura1_paga() -> Q:
    """1ª fatura paga/fechada na visão tratamento (PAGO + OUTROS).

    Inclui PAGO marcado pelo BO (mesmo aguardando confirmação FPD).
    """
    return Q(faturas__numero_fatura=1) & Q(faturas__status__in=STATUS_FATURA_FECHADA)


def _aplicar_filtro_fila(queryset: QuerySet[ContratoM10], fila: str) -> QuerySet[ContratoM10]:
    """Filas de tratamento: atrasados (−60d / +60d) x em aberto x pagas."""
    hoje = timezone.localdate()
    if fila in (FILA_ATRASADOS_LT60, 'atrasados_-60', 'atrasados_menos_60'):
        return queryset.filter(_q_fatura1_atrasada_lt60(hoje)).distinct()
    if fila in (FILA_ATRASADOS_GTE60, 'atrasados_+60', 'atrasados_mais_60'):
        return queryset.filter(_q_fatura1_atrasada_gte60(hoje)).distinct()
    if fila == FILA_ATRASADOS:
        return queryset.filter(_q_fatura1_atrasada(hoje)).distinct()
    if fila in ('abertos', 'em_aberto'):
        return queryset.filter(_q_fatura1_em_aberto(hoje)).distinct()
    if fila in ('pagas', 'pago', 'pagos'):
        return queryset.filter(_q_fatura1_paga()).distinct()
    if fila in ('todos', 'total', ''):
        return queryset.filter(
            _q_fatura1_atrasada(hoje) | _q_fatura1_em_aberto(hoje) | _q_fatura1_paga()
        ).distinct()
    return queryset


def contagens_filas_tratamento(queryset: QuerySet[ContratoM10]) -> dict[str, Any]:
    """Contagens das filas sem aplicar o filtro de fila atual."""
    hoje = timezone.localdate()
    atrasados_lt60 = queryset.filter(_q_fatura1_atrasada_lt60(hoje)).distinct().count()
    atrasados_gte60 = queryset.filter(_q_fatura1_atrasada_gte60(hoje)).distinct().count()
    atrasados = atrasados_lt60 + atrasados_gte60
    abertos = queryset.filter(_q_fatura1_em_aberto(hoje)).distinct().count()
    pagas = queryset.filter(_q_fatura1_paga()).distinct().count()
    total = atrasados + abertos + pagas
    pct_fpd = round(
        ((atrasados + abertos) / total * 100) if total > 0 else 0.0,
        1,
    )
    faltam_meta = faltam_pagamentos_meta_fpd(atrasados, abertos, total, META_FPD_PCT)
    return {
        'atrasados': atrasados,
        'atrasados_lt60': atrasados_lt60,
        'atrasados_gte60': atrasados_gte60,
        'abertos': abertos,
        'pagas': pagas,
        # Total operacional = soma das filas (bate com planilha quando vencimentos estão corretos)
        'todos': total,
        'base': queryset.count(),
        # % FPD = (atrasados + em aberto) / total — inadimplência da 1ª fatura no mês
        'pct_fpd': pct_fpd,
        'meta_fpd_pct': META_FPD_PCT,
        # Pagamentos necessários para chegar a FPD ≤ meta (denominador fixo)
        'faltam_para_meta_fpd': faltam_meta,
        'atraso_limite_fpd_dias': ATRASO_LIMITE_FPD_DIAS,
    }


# Filtros cujas opções exibem contagem — excluídos da base de contagem
_FILTROS_OPCAO_CONTAGEM: frozenset[str] = frozenset({
    'faixa_atraso',
    'faixa',
    'faturas_pagas',
    'faturas_pagas_n',
    'conferencia_fpd',
    'status_tratamento_id',
    'status_tratamento',
    'promessa',
    'vendedor',
})


def contagens_opcoes_filtros(queryset: QuerySet[ContratoM10]) -> dict[str, Any]:
    """Contagens por opção de filtro no contexto atual (mês + fila + demais filtros).

    O queryset deve já estar anotado com ``faturas_pagas`` e sem os filtros
    dimensionais listados em ``_FILTROS_OPCAO_CONTAGEM``.
    """
    hoje = timezone.localdate()
    faixas: dict[str, int] = {}
    for chave, _label in FAIXAS_NIO_ORDEM:
        faixas[chave] = queryset.filter(
            _q_faixa_atraso_fatura1(chave, hoje)
        ).distinct().count()

    faturas_pagas: dict[str, int] = {}
    for n in range(0, 11):
        faturas_pagas[str(n)] = queryset.filter(faturas_pagas=n).count()

    conferencia: dict[str, int] = {}
    for conf in ('AGUARDANDO', 'CONFIRMADO', 'DIVERGENTE'):
        conferencia[conf] = queryset.filter(
            faturas__numero_fatura=1,
            faturas__conferencia_fpd=conf,
        ).distinct().count()

    status_trat: dict[str, int] = {}
    for row in (
        queryset.values('status_tratamento_id')
        .annotate(c=Count('id', distinct=True))
    ):
        key = 'sem' if row['status_tratamento_id'] is None else str(row['status_tratamento_id'])
        status_trat[key] = int(row['c'] or 0)

    # Nickname operacional = username (mesmo padrão de _vendedor_nome)
    vendedores: list[dict[str, Any]] = []
    for row in (
        queryset.filter(vendedor_id__isnull=False)
        .values('vendedor_id', 'vendedor__username')
        .annotate(c=Count('id', distinct=True))
    ):
        vid = row['vendedor_id']
        if not vid:
            continue
        nick = (row.get('vendedor__username') or '').strip() or f'#{vid}'
        vendedores.append({
            'id': vid,
            'nome': nick,
            'count': int(row['c'] or 0),
        })
    vendedores.sort(key=lambda x: x['nome'].lower())

    return {
        'faixa_atraso': faixas,
        'faturas_pagas': faturas_pagas,
        'conferencia_fpd': conferencia,
        'status_tratamento': status_trat,
        'vendedores': vendedores,
    }


def _fatura_envio_id(contrato: ContratoM10, faturas_por_contrato: dict[int, list[FaturaM10]]) -> Optional[int]:
    """Fatura em aberto mais antiga (menor número); fallback fatura 1."""
    faturas = faturas_por_contrato.get(contrato.id, [])
    abertas = [f for f in faturas if not _fatura_esta_fechada(f.status)]
    if abertas:
        abertas.sort(key=lambda f: (f.numero_fatura or 99, f.data_vencimento or date.max))
        return abertas[0].id
    for f in faturas:
        if f.numero_fatura == 1:
            return f.id
    return None


def _resolver_fatura_envio(
    contrato: ContratoM10,
    faturas_por_contrato: dict[int, list[FaturaM10]],
) -> Optional[FaturaM10]:
    fatura_id = _fatura_envio_id(contrato, faturas_por_contrato)
    if not fatura_id:
        return None
    for f in faturas_por_contrato.get(contrato.id, []):
        if f.id == fatura_id:
            return f
    return None


def validar_fatura_para_envio_cobranca(fatura: FaturaM10) -> tuple[bool, str]:
    """
    Impede cobrança WhatsApp/e-mail sem variáveis mínimas do template Meta
    (valor e vencimento). R$ 0,00 ou nulo bloqueia o envio.
    """
    if fatura is None:
        return False, 'Fatura não encontrada.'
    if not getattr(fatura, 'data_vencimento', None):
        return False, (
            'Fatura sem data de vencimento. '
            'Atualize a fatura antes de enviar a cobrança.'
        )
    try:
        valor = float(fatura.valor) if fatura.valor is not None else 0.0
    except (TypeError, ValueError):
        valor = 0.0
    if valor <= 0:
        return False, (
            'Fatura sem valor válido (R$ 0,00 ou vazio). '
            'Atualize o valor da fatura antes de enviar a cobrança.'
        )
    return True, ''


def _iso_dt_local(dt: Any) -> Optional[str]:
    if not dt:
        return None
    try:
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        return dt.isoformat()
    except Exception:
        return str(dt)


def montar_resumo_contatos_por_contrato(
    contratos: list[ContratoM10],
) -> dict[int, dict[str, Any]]:
    """
    Resumo de contatos por contrato para badges na lista:
    whatsapp / email / ligacao (+ resposta se já houver).
    """
    vazio_canal = {'count': 0, 'ultimo_em': None, 'sucesso': None}
    out: dict[int, dict[str, Any]] = {}
    for c in contratos:
        out[c.id] = {
            'whatsapp': dict(vazio_canal),
            'email': dict(vazio_canal),
            'ligacao': dict(vazio_canal),
            'resposta': {'count': 0, 'ultimo_em': None, 'texto': ''},
        }
    if not contratos or HistoricoEnvioQualidade is None:
        return out

    ids = [c.id for c in contratos]
    mapa_venda_para_contrato = {c.venda_id: c.id for c in contratos if c.venda_id}
    canal_map = {
        'WHATSAPP': 'whatsapp',
        'EMAIL': 'email',
        'LIGACAO': 'ligacao',
        'RESPOSTA': 'resposta',
    }

    qs = (
        HistoricoEnvioQualidade.objects.filter(contrato_id__in=ids)
        .order_by('-criado_em')
        .only('contrato_id', 'canal', 'sucesso', 'criado_em', 'mensagem')
    )
    for h in qs.iterator(chunk_size=500):
        bucket = out.get(h.contrato_id)
        if not bucket:
            continue
        key = canal_map.get((h.canal or '').upper())
        if not key:
            continue
        item = bucket[key]
        item['count'] = int(item.get('count') or 0) + 1
        if item.get('ultimo_em') is None:
            item['ultimo_em'] = _iso_dt_local(h.criado_em)
            if key != 'resposta':
                item['sucesso'] = bool(h.sucesso)
            else:
                item['texto'] = (h.mensagem or '')[:120]

    # Ligações da API Sonax ainda não espelhadas no histórico Qualidade
    venda_ids_sem_hist = [
        vid
        for vid, cid in mapa_venda_para_contrato.items()
        if out[cid]['ligacao']['count'] == 0
    ]
    if venda_ids_sem_hist:
        try:
            from django.db.models import Count, Max

            from crm_app.models import AuditoriaLigacao

            agregados = (
                AuditoriaLigacao.objects.filter(venda_id__in=venda_ids_sem_hist)
                .values('venda_id')
                .annotate(n=Count('id'), ultimo=Max('criado_em'))
            )
            for row in agregados:
                cid = mapa_venda_para_contrato.get(row['venda_id'])
                if not cid:
                    continue
                out[cid]['ligacao'] = {
                    'count': int(row['n'] or 0),
                    'ultimo_em': _iso_dt_local(row['ultimo']),
                    'sucesso': True,
                }
        except Exception:
            logger.exception('[Qualidade] Falha ao agregar ligações AuditoriaLigacao')

    return out


def _vendedor_nome(contrato: ContratoM10) -> str:
    """Exibe o nickname (username) do vendedor — padrão operacional do time."""
    if not contrato.vendedor:
        return '-'
    nick = (contrato.vendedor.username or '').strip()
    if nick:
        return nick
    nome = f'{contrato.vendedor.first_name or ""} {contrato.vendedor.last_name or ""}'.strip()
    return nome or '-'


def _id_contrato_fpd(
    contrato: ContratoM10,
    fatura1: Optional[FaturaM10] = None,
) -> str:
    """Número CONTRATO/ID_CONTRATO da planilha FPD.

    Preferência: ContratoM10.numero_contrato_definitivo (preenchido na importação);
    fallback para FaturaM10.id_contrato_fpd da 1ª fatura.
    """
    val = (getattr(contrato, 'numero_contrato_definitivo', None) or '').strip()
    if val:
        return val
    if fatura1 is not None:
        val = (getattr(fatura1, 'id_contrato_fpd', None) or '').strip()
        if val:
            return val
    return ''


def listar_status_tratamento_qualidade() -> list[dict[str, Any]]:
    """Opções cadastradas em Cadastros Gerais (StatusCRM tipo Qualidade)."""
    return list(
        StatusCRM.objects.filter(tipo='Qualidade')
        .order_by('nome')
        .values('id', 'nome', 'cor', 'estado')
    )


def atualizar_status_tratamento_contrato(
    contrato_id: int,
    status_id: Optional[int],
) -> dict[str, Any]:
    """Atualiza o status de tratamento do BO no ContratoM10."""
    contrato = ContratoM10.objects.filter(pk=contrato_id).first()
    if not contrato:
        raise ValueError('Contrato não encontrado')

    if status_id in (None, '', 0, '0', 'null'):
        contrato.status_tratamento = None
        contrato.save(update_fields=['status_tratamento', 'atualizado_em'])
        return {
            'ok': True,
            'contrato_id': contrato.id,
            'status_tratamento_id': None,
            'status_tratamento_nome': None,
            'status_tratamento_cor': None,
        }

    status_obj = StatusCRM.objects.filter(pk=int(status_id), tipo='Qualidade').first()
    if not status_obj:
        raise ValueError('Status de Qualidade inválido. Cadastre em Cadastros Gerais → Status (tipo Qualidade).')

    contrato.status_tratamento = status_obj
    contrato.save(update_fields=['status_tratamento', 'atualizado_em'])
    return {
        'ok': True,
        'contrato_id': contrato.id,
        'status_tratamento_id': status_obj.id,
        'status_tratamento_nome': status_obj.nome,
        'status_tratamento_cor': status_obj.cor,
    }


def dashboard_qualidade(
    lente: str,
    mes: str,
    user: Any,
    filtros: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Monta KPIs + lista paginada de contratos para a lente/mês informados.

    Com busca textual (``q`` com 2+ caracteres), ignora o filtro de mês/safra
    e pesquisa em toda a base — o BO frequentemente não sabe o mês da fatura.
    """
    filtros = filtros or {}
    lente_norm = (lente or LENTE_VENCIMENTO).strip().lower()
    ver_bonus = pode_ver_valor_bonus(user)

    status_display_map = dict(FaturaM10.STATUS_CHOICES)

    busca_raw = (filtros.get('q') or filtros.get('busca') or '').strip()
    busca_geral = len(busca_raw) >= 2

    if busca_geral:
        # Busca em toda a base (todas as safras / meses)
        queryset = ContratoM10.objects.all()
    else:
        data_inicio, data_fim = mes_range(mes)
        if lente_norm == LENTE_INSTALACAO:
            queryset = ContratoM10.objects.filter(
                data_instalacao__gte=data_inicio,
                data_instalacao__lt=data_fim,
            )
        else:
            # Lente vencimento: mesmo universo do Dashboard FPD (planilha MATCHED).
            # Usa dt_venc_orig da ImportacaoFPD — não FaturaM10.data_vencimento —
            # para não divergir quando o CRM ficou com vencimento recalculado
            # (ex.: instalação+25) diferente da planilha.
            contrato_ids = (
                ImportacaoFPD.objects.filter(
                    indicador='FPD',
                    dt_venc_orig__gte=data_inicio,
                    dt_venc_orig__lt=data_fim,
                    match_status='MATCHED',
                    contrato_m10_id__isnull=False,
                )
                .values_list('contrato_m10_id', flat=True)
                .distinct()
            )
            queryset = ContratoM10.objects.filter(id__in=contrato_ids)

    # Órfãos ficam fora do tratamento por padrão (contam em "Faltam no CRM" / modal órfãos)
    if filtros.get('orfao') in (None, '') and _contrato_tem_campo('orfao'):
        queryset = queryset.filter(orfao=False)

    # Lembrete de promessa: conta no universo do mês (antes dos filtros dimensionais)
    promessas = contagens_promessas(queryset)

    # Base para contagens das opções de filtro (sem faixa/status trat./conf./N-10)
    filtros_contagem = {
        k: v for k, v in filtros.items() if k not in _FILTROS_OPCAO_CONTAGEM
    }
    qs_base_annot = (
        _aplicar_filtros_contratos(queryset, filtros_contagem)
        .annotate(
            total_faturas=Count('faturas', distinct=True),
            faturas_pagas=Count(
                'faturas',
                filter=Q(faturas__status__in=STATUS_FATURA_FECHADA),
                distinct=True,
            ),
        )
    )

    fila = (filtros.get('fila') or 'todos').strip().lower()
    qs_para_opcoes = _aplicar_filtro_fila(qs_base_annot, fila) if fila else qs_base_annot
    contagens_filtros = contagens_opcoes_filtros(qs_para_opcoes)

    # QS completo (todos os filtros dimensionais) — filas usam o QS sem filtro de fila
    queryset = (
        _aplicar_filtros_contratos(queryset, filtros)
        .select_related('vendedor', 'venda', 'venda__cliente', 'status_tratamento')
        .annotate(
            total_faturas=Count('faturas', distinct=True),
            faturas_pagas=Count(
                'faturas',
                filter=Q(faturas__status__in=STATUS_FATURA_FECHADA),
                distinct=True,
            ),
        )
        .order_by('-data_instalacao', 'id')
    )

    # Filtro N/10 depois do annotate para reutilizar faturas_pagas
    faturas_pagas_n = filtros.get('faturas_pagas') or filtros.get('faturas_pagas_n')
    if faturas_pagas_n not in (None, ''):
        try:
            n_pagas = int(str(faturas_pagas_n).split('/')[0].strip())
        except (TypeError, ValueError):
            n_pagas = None
        if n_pagas is not None and 0 <= n_pagas <= 10:
            queryset = queryset.filter(faturas_pagas=n_pagas)

    filas = contagens_filas_tratamento(queryset)
    reconciliacao = (
        None if busca_geral
        else reconciliar_fpd_com_painel(mes, filas, lente=lente_norm)
    )
    if fila:
        queryset = _aplicar_filtro_fila(queryset, fila)

    contratos_list = list(queryset)
    for c in contratos_list:
        if c.total_faturas == 0 and c.status_fatura_fpd and str(c.status_fatura_fpd).lower().startswith('paga'):
            c.total_faturas = 1
            c.faturas_pagas = 1

    ids_contratos = [c.id for c in contratos_list]
    faturas_qs = FaturaM10.objects.filter(contrato_id__in=ids_contratos).order_by(
        'contrato_id', 'numero_fatura'
    )
    faturas_por_contrato: dict[int, list[FaturaM10]] = {}
    faturas1_map: dict[int, FaturaM10] = {}
    for f in faturas_qs:
        faturas_por_contrato.setdefault(f.contrato_id, []).append(f)
        if f.numero_fatura == 1:
            faturas1_map[f.contrato_id] = f

    total = len(contratos_list)
    ativos = sum(1 for c in contratos_list if c.status_contrato == 'ATIVO')
    elegiveis = sum(1 for c in contratos_list if _contrato_elegivel_dinamico(c))
    valor_total = elegiveis * VALOR_BONUS_M10 if ver_bonus else 0

    if lente_norm == LENTE_VENCIMENTO:
        f1_ids = [faturas1_map[c.id].id for c in contratos_list if c.id in faturas1_map]
        f1_qs = FaturaM10.objects.filter(id__in=f1_ids) if f1_ids else FaturaM10.objects.none()
        total_f1 = f1_qs.count()
        pagas_f1 = f1_qs.filter(status__in=STATUS_FATURA_FECHADA).count()
        abertas_f1 = total_f1 - pagas_f1
        taxa = round((abertas_f1 / total_f1 * 100) if total_f1 > 0 else 0, 1)
        kpis: dict[str, Any] = {
            'total': total,
            'geradas': total_f1,
            'pagas': pagas_f1,
            'abertas': abertas_f1,
            'taxa_fpd': taxa,
            'ativos': ativos,
            'elegiveis': elegiveis,
            'valor_total': valor_total,
            'pode_ver_valor_bonus': ver_bonus,
        }
    else:
        taxa_permanencia = round((ativos / total * 100) if total > 0 else 0, 1)
        kpis = {
            'total': total,
            'instalados': total,
            'ativos': ativos,
            'elegiveis': elegiveis,
            'valor_total': valor_total,
            'taxa_permanencia': taxa_permanencia,
            'pode_ver_valor_bonus': ver_bonus,
        }

    try:
        page = max(1, int(filtros.get('page', 1) or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(250, int(filtros.get('page_size', 100) or 100)))
    except (TypeError, ValueError):
        page_size = 100
    start = (page - 1) * page_size
    end = start + page_size
    total_pages = (total + page_size - 1) // page_size if total else 0

    contratos_data: list[dict[str, Any]] = []
    pagina_contratos = contratos_list[start:end]
    resumo_contatos = montar_resumo_contatos_por_contrato(pagina_contratos)
    for c in pagina_contratos:
        is_elegivel = _contrato_elegivel_dinamico(c)
        f1 = faturas1_map.get(c.id)
        status_fatura1 = f1.status if f1 else (c.status_fatura_fpd or None)
        status_fatura1_display = (
            status_display_map.get(f1.status, f1.status) if f1 else (c.status_fatura_fpd or '-')
        )
        orfao = _eh_orfao(c)
        contato = enriquecer_contato_contrato(c)
        valor_bonus: Optional[int]
        if not ver_bonus:
            valor_bonus = None
        else:
            valor_bonus = VALOR_BONUS_M10 if is_elegivel else 0

        data_venc_f1 = f1.data_vencimento.isoformat() if f1 and f1.data_vencimento else None
        if f1 and f1.data_vencimento:
            mes_ref = f1.data_vencimento.strftime('%Y-%m')
        elif c.data_instalacao:
            mes_ref = c.data_instalacao.strftime('%Y-%m')
        else:
            mes_ref = (c.safra or '')[:7]
        valor_fatura1: Optional[float] = None
        if f1 is not None and f1.valor is not None:
            try:
                valor_fatura1 = float(f1.valor)
            except (TypeError, ValueError):
                valor_fatura1 = None
        st = getattr(c, 'status_tratamento', None)
        fatura_envio = _resolver_fatura_envio(c, faturas_por_contrato)
        valor_envio: Optional[float] = None
        venc_envio: Optional[str] = None
        pode_enviar_cobranca = False
        motivo_bloqueio_envio = 'Nenhuma fatura disponível para cobrança.'
        if fatura_envio is not None:
            try:
                valor_envio = (
                    float(fatura_envio.valor) if fatura_envio.valor is not None else None
                )
            except (TypeError, ValueError):
                valor_envio = None
            venc_envio = (
                fatura_envio.data_vencimento.isoformat()
                if fatura_envio.data_vencimento
                else None
            )
            pode_enviar_cobranca, motivo_bloqueio_envio = validar_fatura_para_envio_cobranca(
                fatura_envio
            )
        promessa_info = _promessa_aberta_contrato(
            faturas_por_contrato.get(c.id, []),
            timezone.localdate(),
        )
        contratos_data.append({
            'id': c.id,
            'venda_id': c.venda_id,
            'ordem_servico': c.ordem_servico or '-',
            'id_contrato': _id_contrato_fpd(c, f1),
            'cliente_nome': c.cliente_nome,
            'cpf_cliente': (c.cpf_cliente or '').strip(),
            'vendedor_nome': _vendedor_nome(c),
            'status_contrato': c.status_contrato,
            'status_fatura1': status_fatura1,
            'status_fatura1_display': status_fatura1_display,
            'conferencia_fpd': (f1.conferencia_fpd if f1 else '') or '',
            'fatura1_id': f1.id if f1 else None,
            'status_origem': (f1.status_origem if f1 else '') or '',
            'ds_status_fatura_fpd': (f1.ds_status_fatura_fpd if f1 else '') or '',
            'data_vencimento_f1': data_venc_f1,
            'mes_ref': mes_ref,
            'safra': (c.safra or '')[:7],
            'valor_fatura1': valor_fatura1,
            'data_promessa_pagamento': (promessa_info or {}).get('data') or '',
            'promessa_faixa': (promessa_info or {}).get('faixa') or '',
            'promessa_numero_fatura': (promessa_info or {}).get('numero_fatura'),
            'status_tratamento_id': st.id if st else None,
            'status_tratamento_nome': st.nome if st else None,
            'status_tratamento_cor': st.cor if st else None,
            'faturas_pagas': c.faturas_pagas,
            'total_faturas': c.total_faturas,
            'elegivel': is_elegivel,
            'valor_bonus': valor_bonus,
            'orfao': orfao,
            'pode_tratar': pode_tratar_contrato(c),
            'telefone': contato.get('telefone') or contato.get('telefone1'),
            'telefone2': contato.get('telefone2'),
            'email': contato.get('email'),
            'fatura_envio_id': fatura_envio.id if fatura_envio else None,
            'valor_envio': valor_envio,
            'vencimento_envio': venc_envio,
            'pode_enviar_cobranca': pode_enviar_cobranca,
            'motivo_bloqueio_envio': motivo_bloqueio_envio if not pode_enviar_cobranca else '',
            'contatos': resumo_contatos.get(c.id) or {},
        })

    return {
        'lente': lente_norm,
        'mes': mes,
        'label': _label_mes(mes),
        'busca_geral': busca_geral,
        'kpis': kpis,
        'filas': filas,
        'contagens_filtros': contagens_filtros,
        'promessas': promessas,
        'reconciliacao': reconciliacao,
        'fila': fila if fila else 'todos',
        'status_tratamento_opcoes': listar_status_tratamento_qualidade(),
        'contratos': contratos_data,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'total': total,
        'pode_ver_valor_bonus': ver_bonus,
    }


def reconciliar_fpd_com_painel(
    mes: str,
    filas: dict[str, int],
    *,
    lente: str = 'vencimento',
) -> dict[str, Any]:
    """Compara totais da planilha FPD com as filas do painel (atrasados/abertos/pagas)."""
    data_inicio, data_fim = mes_range(mes)
    atrasados = int(filas.get('atrasados') or 0)
    abertos = int(filas.get('abertos') or 0)
    pagas = int(filas.get('pagas') or 0)
    painel_total = atrasados + abertos + pagas
    painel_abertas = atrasados + abertos

    qs_fpd = ImportacaoFPD.objects.filter(
        indicador='FPD',
        dt_venc_orig__gte=data_inicio,
        dt_venc_orig__lt=data_fim,
    )
    fpd_total = qs_fpd.count()
    fpd_abertas = qs_fpd.filter(ds_sit_fatura__iexact='ABERTA').count()
    fpd_fechadas = qs_fpd.filter(ds_sit_fatura__iexact='FECHADA').count()
    fpd_abertas_matched = qs_fpd.filter(
        ds_sit_fatura__iexact='ABERTA', match_status='MATCHED'
    ).count()
    fpd_total_matched = qs_fpd.filter(match_status='MATCHED').count()
    faltam_crm = qs_fpd.filter(match_status='FALTA_CRM').count()
    faltam_crm_abertas = qs_fpd.filter(
        match_status='FALTA_CRM', ds_sit_fatura__iexact='ABERTA'
    ).count()

    # PAGO no tratamento ainda aguardando/divergente da planilha (explica Δ abertas)
    # Mesmo universo do painel: ImportacaoFPD MATCHED do mês (não data_vencimento CRM)
    contrato_ids_mes = ImportacaoFPD.objects.filter(
        indicador='FPD',
        dt_venc_orig__gte=data_inicio,
        dt_venc_orig__lt=data_fim,
        match_status='MATCHED',
        contrato_m10_id__isnull=False,
    ).values_list('contrato_m10_id', flat=True)
    aguard_fpd = FaturaM10.objects.filter(
        numero_fatura=1,
        contrato_id__in=contrato_ids_mes,
        status='PAGO',
        conferencia_fpd__in=['AGUARDANDO', 'DIVERGENTE'],
    ).count()
    diff_abertas = fpd_abertas_matched - painel_abertas
    # Bate com o tratamento quando a diferença da planilha = aguardando conf. FPD
    bate_tratamento = (
        fpd_total_matched == painel_total
        and diff_abertas == aguard_fpd
    )

    return {
        'mes': mes,
        'lente': lente,
        'fpd_total_planilha': fpd_total,
        'fpd_fechadas_planilha': fpd_fechadas,
        'fpd_abertas_planilha': fpd_abertas,
        'fpd_total_vinculadas': fpd_total_matched,
        'fpd_abertas_vinculadas': fpd_abertas_matched,
        'painel_atrasados': atrasados,
        'painel_abertos': abertos,
        'painel_pagas': pagas,
        'painel_total': painel_total,
        'painel_atrasados_abertos': painel_abertas,
        'painel_aguard_fpd': aguard_fpd,
        'diferenca_total': fpd_total_matched - painel_total,
        'diferenca_abertas': diff_abertas,
        'faltam_crm_fpd': faltam_crm,
        'faltam_crm_fpd_abertas': faltam_crm_abertas,
        'bate_total': fpd_total_matched == painel_total,
        'bate': bate_tratamento,
        'bate_planilha_pura': fpd_abertas_matched == painel_abertas,
    }


# Faixas da planilha → rótulos do dashboard Nio / filtro Tratamento
FAIXAS_NIO_ORDEM = [
    ('d10_15', '10 a 15 Dias'),
    ('d15_30', '15 a 30 Dias'),
    ('d30_45', '30 a 45 Dias'),
    ('d45_59', '45 a 59 Dias'),
    ('d61', '>= 60 Dias'),
]

# Limites inclusivos de dias de atraso (fatura 1) para filtro do painel
FAIXA_ATRASO_RANGES: dict[str, tuple[int, Optional[int]]] = {
    'd10_15': (0, 15),
    'd15_30': (16, 30),
    'd30_45': (31, 45),
    'd45_59': (46, 59),
    'd61': (60, None),
    # Legado (planilhas antigas / UI antiga)
    'd45_55': (46, 59),
    'd55_60': (46, 59),
}


def _faixa_por_dias_vivos(dias_atraso: int) -> str:
    """Categoriza dias de atraso (calculados ao vivo) nas chaves do dashboard."""
    try:
        d = int(dias_atraso or 0)
    except (TypeError, ValueError):
        d = 0
    if d < 0:
        d = 0
    if d <= 15:
        return 'd10_15'
    if d <= 30:
        return 'd15_30'
    if d <= 45:
        return 'd30_45'
    if d <= 59:
        return 'd45_59'
    return 'd61'


def _dias_atraso_por_vencimento(vencimento: Optional[date], hoje: Optional[date] = None) -> int:
    """Dias em aberto desde o vencimento (0 se ainda não venceu)."""
    if not vencimento:
        return 0
    ref = hoje or timezone.localdate()
    try:
        return max(0, (ref - vencimento).days)
    except Exception:
        return 0


def _normalizar_faixa_nio(faixa: str, dias_atraso: int = 0) -> str:
    """Mapeia FAIXA da planilha (ou dias) para chave do dashboard estilo Nio."""
    f = (faixa or '').strip().upper().replace('Á', 'A')
    f = re.sub(r'\s+', ' ', f)
    if '0 A 15' in f or '10 A 15' in f or '0-15' in f or '10-15' in f:
        return 'd10_15'
    if '15 A 30' in f or '15-30' in f:
        return 'd15_30'
    if '30 A 45' in f or '30-45' in f:
        return 'd30_45'
    if '45 A 59' in f or '45-59' in f or '45 A 55' in f or '45-55' in f:
        return 'd45_59'
    if '55 A 60' in f or '55-60' in f or '45 A 60' in f:
        return 'd45_59'
    if '>60' in f or '>=' in f or '61' in f or 'MAIS DE 60' in f:
        return 'd61'

    return _faixa_por_dias_vivos(dias_atraso)


def _q_faixa_atraso_fatura1(faixa_chave: str, hoje: date) -> Q:
    """Filtro de contratos pela faixa de atraso da 1ª fatura (ao vivo pelo vencimento)."""
    chave = (faixa_chave or '').strip().lower()
    limites = FAIXA_ATRASO_RANGES.get(chave)
    if not limites:
        return Q()
    lo, hi = limites
    from datetime import timedelta

    base = Q(faturas__numero_fatura=1) & ~Q(faturas__status__in=STATUS_FATURA_FECHADA)
    # Sempre calcula pela data de vencimento (não depende de dias_atraso congelado da planilha)
    if hi is None:
        return base & Q(faturas__data_vencimento__lte=hoje - timedelta(days=lo))
    return base & Q(
        faturas__data_vencimento__gte=hoje - timedelta(days=hi),
        faturas__data_vencimento__lte=hoje - timedelta(days=lo),
    )


def dashboard_fpd_estilo_nio(
    *,
    indicador: str = 'FPD',
    meses: Optional[int] = 6,
    vendedor_id: Optional[int] = None,
    nm_seg: Optional[str] = None,
    modo: str = 'geral',
) -> dict[str, Any]:
    """Monta tabela no formato do dashboard Nio (colunas = meses de vencimento).

    Base: linhas da ``ImportacaoFPD`` (universo da planilha).
    Status pago/aberto: prioriza o tratamento do BO em ``FaturaM10``.
    Faixas de atraso: **ao vivo** pela data de vencimento
    (CRM ``FaturaM10.data_vencimento`` se houver; senão ``dt_venc_orig`` da planilha).
    A faixa/dias da planilha entram só no confronto (divergências).

    ``vendedor_id`` filtra pelo vendedor do CRM (``ContratoM10.vendedor``).
    Com filtro, a UI usa visão resumida (pagas/abertas/total/% aberto).

    ``nm_seg`` filtra pelo segmento da planilha (Varejo / Empresarial).

    ``modo=por_vendedor``: linhas = vendedores; cada mês com total/pagas/abertas;
    coluna % Aberto no período.
    """
    modo_eff = (modo or 'geral').strip().lower()
    if modo_eff in ('por_vendedor', 'vendedores', 'vendedor'):
        return dashboard_fpd_por_vendedor(
            indicador=indicador,
            meses=meses,
            nm_seg=nm_seg,
        )

    ind = (indicador or 'FPD').strip().upper()
    if ind not in ('FPD', 'SPD', 'TPD'):
        ind = 'FPD'
    numero_fatura = INDICADOR_PARA_NUMERO_FATURA.get(ind, 1)
    try:
        n_meses = max(1, min(12, int(meses or 6)))
    except (TypeError, ValueError):
        n_meses = 6

    vend_id: Optional[int] = None
    if vendedor_id not in (None, '', '0', 0, 'todos'):
        try:
            vend_id = int(vendedor_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            vend_id = None

    seg_filtro = _normalizar_filtro_nm_seg(nm_seg)

    hoje = timezone.localdate()

    qs_universo = ImportacaoFPD.objects.filter(indicador=ind, dt_venc_orig__isnull=False)
    # Janela de meses alinhada ao universo (mesmo com filtro de vendedor/segmento)
    meses_disponiveis = sorted({
        d.strftime('%Y%m')
        for d in qs_universo.dates('dt_venc_orig', 'month')
        if d
    })
    meses_ord = meses_disponiveis[-n_meses:] if meses_disponiveis else []

    qs_imp = qs_universo
    if vend_id:
        qs_imp = qs_imp.filter(contrato_m10__vendedor_id=vend_id)
    if seg_filtro:
        qs_imp = qs_imp.filter(nm_seg__iexact=seg_filtro)

    qs = list(
        qs_imp.values(
            'dt_venc_orig',
            'ds_sit_fatura',
            'faixa',
            'nr_dias_atraso',
            'contrato_m10_id',
            'numero_fatura_m10',
        )
    )

    contrato_ids = {
        row['contrato_m10_id']
        for row in qs
        if row.get('contrato_m10_id')
    }
    # status + conferência + vencimento da fatura N no CRM (tratamento)
    fatura_crm: dict[int, dict[str, Any]] = {}
    if contrato_ids:
        for cid, st, conf, venc in FaturaM10.objects.filter(
            contrato_id__in=contrato_ids,
            numero_fatura=numero_fatura,
        ).values_list('contrato_id', 'status', 'conferencia_fpd', 'data_vencimento'):
            fatura_crm[cid] = {
                'status': (st or '').upper(),
                'conferencia_fpd': (conf or '').upper(),
                'data_vencimento': venc,
            }

    # Pré-seed dos meses da janela (zeros quando o vendedor não tem volume no mês)
    por_mes: dict[str, dict[str, Any]] = {}
    for chave in meses_ord:
        ano, mes = int(chave[:4]), int(chave[4:6])
        mes_iso = f'{ano:04d}-{mes:02d}'
        por_mes[chave] = {
            'mes_fatura': chave,
            'mes': mes_iso,
            'label': _label_mes(mes_iso),
            'fatura_paga': 0,
            'aguard_fpd': 0,
            'total_fatura': 0,
            'faixas': {k: 0 for k, _ in FAIXAS_NIO_ORDEM},
            'divergencias_faixa': 0,
        }

    abertas_total = 0
    divergencias_faixa = 0
    for row in qs:
        dt = row['dt_venc_orig']
        if not dt:
            continue
        chave = dt.strftime('%Y%m')
        if chave not in por_mes:
            continue
        bucket = por_mes[chave]
        bucket['total_fatura'] += 1

        cid = row.get('contrato_m10_id')
        crm = fatura_crm.get(cid) if cid else None
        sit = (row['ds_sit_fatura'] or '').strip().upper()

        esta_aberta = False
        if crm:
            st_crm = crm['status']
            conf = crm['conferencia_fpd']
            if st_crm in STATUS_FATURA_FECHADA:
                bucket['fatura_paga'] += 1
                if st_crm == 'PAGO' and conf in ('AGUARDANDO', 'DIVERGENTE'):
                    bucket['aguard_fpd'] += 1
            else:
                esta_aberta = True
        elif sit == 'FECHADA':
            bucket['fatura_paga'] += 1
        elif sit == 'ABERTA':
            esta_aberta = True
        else:
            if (row.get('nr_dias_atraso') or 0) <= 0 and not (row.get('faixa') or '').strip():
                bucket['fatura_paga'] += 1
            else:
                esta_aberta = True

        if not esta_aberta:
            continue

        # Vencimento preferencial: CRM; fallback planilha
        venc_vivo = None
        if crm and crm.get('data_vencimento'):
            venc_vivo = crm['data_vencimento']
        else:
            venc_vivo = dt

        dias_vivos = _dias_atraso_por_vencimento(venc_vivo, hoje)
        fk = _faixa_por_dias_vivos(dias_vivos)
        bucket['faixas'][fk] = bucket['faixas'].get(fk, 0) + 1
        abertas_total += 1

        # Confronto com faixa/dias da planilha (snapshot da importação)
        fk_planilha = _normalizar_faixa_nio(
            row.get('faixa') or '', row.get('nr_dias_atraso') or 0
        )
        if fk_planilha != fk:
            bucket['divergencias_faixa'] += 1
            divergencias_faixa += 1

    colunas = []
    for chave in meses_ord:
        b = por_mes[chave]
        abertas = sum(b['faixas'].values())
        total = b['total_fatura']
        pct = round((abertas / total * 100), 2) if total else 0.0
        colunas.append({
            'mes_fatura': b['mes_fatura'],
            'mes': b['mes'],
            'label': b['label'],
            'fatura_paga': b['fatura_paga'],
            'fatura_aberta': abertas,
            'aguard_fpd': b['aguard_fpd'],
            'total_fatura': total,
            'pct_aberto': pct,
            'abertas': abertas,
            'faixas': b['faixas'],
            'divergencias_faixa_planilha': b['divergencias_faixa'],
        })

    # Visão por vendedor: resumo objetivo (pagas / abertas / total / %)
    modo_resumo = bool(vend_id)

    linhas = [
        {'chave': 'mes_fatura', 'label': 'MÊS FATURA', 'tipo': 'header'},
        {'chave': 'fatura_paga', 'label': 'FATURA PAGA', 'tipo': 'metric'},
        {'chave': 'fatura_aberta', 'label': 'FATURA ABERTA', 'tipo': 'metric'},
    ]
    if not modo_resumo:
        linhas.append({'chave': 'aguard_fpd', 'label': 'AGUARD. CONF. FPD', 'tipo': 'metric'})
    linhas.extend([
        {'chave': 'total_fatura', 'label': 'TOTAL FATURA', 'tipo': 'metric'},
        {'chave': 'pct_aberto', 'label': '% ABERTO', 'tipo': 'pct'},
    ])
    if not modo_resumo:
        for fk, label in FAIXAS_NIO_ORDEM:
            linhas.append({'chave': fk, 'label': label, 'tipo': 'faixa'})

    vendedores = _listar_vendedores_dashboard_fpd(ind)
    segmentos = _listar_segmentos_dashboard_fpd(ind)
    vend_sel = None
    if vend_id:
        for v in vendedores:
            if v['id'] == vend_id:
                vend_sel = v
                break
        if not vend_sel:
            vend_sel = {'id': vend_id, 'nome': f'Vendedor #{vend_id}'}

    fonte_partes = [
        'Faixas ao vivo (vencimento CRM/planilha)',
        'pago/aberto = Tratamento',
        'universo = ImportacaoFPD',
    ]
    if vend_sel:
        fonte_partes.append(f'vendedor CRM: {vend_sel["nome"]}')
    if seg_filtro:
        fonte_partes.append(f'nm_seg: {seg_filtro}')

    return {
        'modo': 'geral',
        'indicador': ind,
        'colunas': colunas,
        'linhas': linhas,
        'faixas_ordem': (
            [] if modo_resumo
            else [{'chave': k, 'label': lbl} for k, lbl in FAIXAS_NIO_ORDEM]
        ),
        'fonte': ' · '.join(fonte_partes),
        'faixas_ao_vivo': True,
        'referencia_dias': hoje.isoformat(),
        'abertas_total': abertas_total,
        'divergencias_faixa_planilha': divergencias_faixa,
        'modo_resumo': modo_resumo,
        'vendedor_id': vend_id,
        'vendedor': vend_sel,
        'vendedores': vendedores,
        'nm_seg': seg_filtro,
        'segmentos': segmentos,
    }


def _classificar_pago_aberto_fpd(
    *,
    crm: Optional[dict[str, Any]],
    sit_planilha: str,
    nr_dias_atraso: Any = 0,
    faixa_planilha: str = '',
) -> tuple[bool, bool]:
    """
    Retorna (esta_aberta, contou_paga).
    Prioriza CRM; fallback situação da planilha.
    """
    if crm:
        st_crm = (crm.get('status') or '').upper()
        if st_crm in STATUS_FATURA_FECHADA:
            return False, True
        return True, False

    sit = (sit_planilha or '').strip().upper()
    if sit == 'FECHADA':
        return False, True
    if sit == 'ABERTA':
        return True, False
    if (nr_dias_atraso or 0) <= 0 and not (faixa_planilha or '').strip():
        return False, True
    return True, False


def _nome_vendedor_de_row(row: dict[str, Any]) -> tuple[Optional[int], str]:
    """Nickname operacional = username (padrão do time / _vendedor_nome)."""
    vid = row.get('contrato_m10__vendedor_id') or row.get('vendedor_id')
    if not vid:
        return None, 'sem-vendedor'
    nick = (row.get('contrato_m10__vendedor__username') or '').strip()
    if nick:
        return int(vid), nick
    return int(vid), f'#{vid}'


def dashboard_fpd_por_vendedor(
    *,
    indicador: str = 'FPD',
    meses: Optional[int] = 6,
    nm_seg: Optional[str] = None,
) -> dict[str, Any]:
    """Matriz: linhas = vendedores CRM; colunas = meses (total / pagas / abertas).

    Inclui coluna % Aberto (FPD) no período selecionado.
    Ordena do maior % aberto para o menor.
    """
    ind = (indicador or 'FPD').strip().upper()
    if ind not in ('FPD', 'SPD', 'TPD'):
        ind = 'FPD'
    numero_fatura = INDICADOR_PARA_NUMERO_FATURA.get(ind, 1)
    try:
        n_meses = max(1, min(12, int(meses or 6)))
    except (TypeError, ValueError):
        n_meses = 6

    seg_filtro = _normalizar_filtro_nm_seg(nm_seg)

    qs_universo = ImportacaoFPD.objects.filter(indicador=ind, dt_venc_orig__isnull=False)
    meses_disponiveis = sorted({
        d.strftime('%Y%m')
        for d in qs_universo.dates('dt_venc_orig', 'month')
        if d
    })
    meses_ord = meses_disponiveis[-n_meses:] if meses_disponiveis else []

    colunas_meta = []
    for chave in meses_ord:
        ano, mes = int(chave[:4]), int(chave[4:6])
        mes_iso = f'{ano:04d}-{mes:02d}'
        colunas_meta.append({
            'mes_fatura': chave,
            'mes': mes_iso,
            'label': _label_mes(mes_iso),
        })

    qs_imp = qs_universo
    if seg_filtro:
        qs_imp = qs_imp.filter(nm_seg__iexact=seg_filtro)

    qs = list(
        qs_imp.values(
            'dt_venc_orig',
            'ds_sit_fatura',
            'faixa',
            'nr_dias_atraso',
            'contrato_m10_id',
            'contrato_m10__vendedor_id',
            'contrato_m10__vendedor__username',
            'contrato_m10__vendedor__first_name',
            'contrato_m10__vendedor__last_name',
        )
    )

    contrato_ids = {
        row['contrato_m10_id']
        for row in qs
        if row.get('contrato_m10_id')
    }
    fatura_crm: dict[int, dict[str, Any]] = {}
    if contrato_ids:
        for cid, st, conf, venc in FaturaM10.objects.filter(
            contrato_id__in=contrato_ids,
            numero_fatura=numero_fatura,
        ).values_list('contrato_id', 'status', 'conferencia_fpd', 'data_vencimento'):
            fatura_crm[cid] = {
                'status': (st or '').upper(),
                'conferencia_fpd': (conf or '').upper(),
                'data_vencimento': venc,
            }

    def _bucket_vazio() -> dict[str, int]:
        return {'total': 0, 'pagas': 0, 'abertas': 0}

    # vendedor_key -> { nome, meses: {YYYYMM: bucket}, totais }
    por_vend: dict[str, dict[str, Any]] = {}

    for row in qs:
        dt = row.get('dt_venc_orig')
        if not dt:
            continue
        chave_mes = dt.strftime('%Y%m')
        if chave_mes not in meses_ord:
            continue

        vid, nome = _nome_vendedor_de_row(row)
        key = str(vid) if vid is not None else 'sem'
        block = por_vend.setdefault(
            key,
            {
                'vendedor_id': vid,
                'vendedor_nome': nome,
                'meses': {m: _bucket_vazio() for m in meses_ord},
                'total': 0,
                'pagas': 0,
                'abertas': 0,
            },
        )

        cid = row.get('contrato_m10_id')
        crm = fatura_crm.get(cid) if cid else None
        esta_aberta, contou_paga = _classificar_pago_aberto_fpd(
            crm=crm,
            sit_planilha=row.get('ds_sit_fatura') or '',
            nr_dias_atraso=row.get('nr_dias_atraso') or 0,
            faixa_planilha=row.get('faixa') or '',
        )

        m_bucket = block['meses'][chave_mes]
        m_bucket['total'] += 1
        block['total'] += 1
        if esta_aberta:
            m_bucket['abertas'] += 1
            block['abertas'] += 1
        elif contou_paga:
            m_bucket['pagas'] += 1
            block['pagas'] += 1

    linhas: list[dict[str, Any]] = []
    tot_geral = _bucket_vazio()
    totais_mes = {m: _bucket_vazio() for m in meses_ord}

    for block in por_vend.values():
        total = int(block['total'])
        abertas = int(block['abertas'])
        pagas = int(block['pagas'])
        # Só listar quem tem volume (paga ou aberta) no período
        if total <= 0 or (pagas + abertas) <= 0:
            continue
        pct = round((abertas / total * 100), 2) if total else 0.0
        meses_out = {}
        for m in meses_ord:
            b = block['meses'][m]
            m_total = int(b['total'])
            m_abertas = int(b['abertas'])
            m_pct = round((m_abertas / m_total * 100), 2) if m_total else None
            meses_out[m] = {
                'total': m_total,
                'pagas': int(b['pagas']),
                'abertas': m_abertas,
                'pct_aberto': m_pct,
            }
            totais_mes[m]['total'] += m_total
            totais_mes[m]['pagas'] += int(b['pagas'])
            totais_mes[m]['abertas'] += m_abertas
        tot_geral['total'] += total
        tot_geral['pagas'] += pagas
        tot_geral['abertas'] += abertas
        linhas.append({
            'vendedor_id': block['vendedor_id'],
            'vendedor_nome': block['vendedor_nome'],
            'meses': meses_out,
            'total': total,
            'pagas': pagas,
            'abertas': abertas,
            'pct_aberto': pct,
        })

    for m in meses_ord:
        tm = totais_mes[m]
        tm_total = int(tm['total'])
        tm['pct_aberto'] = (
            round((int(tm['abertas']) / tm_total * 100), 2) if tm_total else None
        )

    # Maior FPD do período (pior) primeiro; depois nickname
    linhas.sort(key=lambda x: (-x['pct_aberto'], x['vendedor_nome'].lower()))

    pct_geral = (
        round((tot_geral['abertas'] / tot_geral['total'] * 100), 2)
        if tot_geral['total']
        else 0.0
    )

    return {
        'modo': 'por_vendedor',
        'indicador': ind,
        'colunas': colunas_meta,
        'linhas_vendedores': linhas,
        'totais': {
            'meses': totais_mes,
            'total': tot_geral['total'],
            'pagas': tot_geral['pagas'],
            'abertas': tot_geral['abertas'],
            'pct_aberto': pct_geral,
        },
        'legenda_celula': 'T = total · P = pagas · A = abertas · % = aberto no mês',
        'fonte': (
            'Visão por vendedor CRM · pago/aberto = Tratamento · '
            'universo = ImportacaoFPD · % Aberto = abertas ÷ total de cada mês'
            + (f' · nm_seg: {seg_filtro}' if seg_filtro else '')
        ),
        'vendedores': _listar_vendedores_dashboard_fpd(ind),
        'nm_seg': seg_filtro,
        'segmentos': _listar_segmentos_dashboard_fpd(ind),
        'modo_resumo': False,
        'vendedor_id': None,
        'vendedor': None,
        # Compat: UI geral espera colunas/linhas vazias se não usadas
        'linhas': [],
        'faixas_ordem': [],
        'faixas_ao_vivo': False,
        'abertas_total': tot_geral['abertas'],
        'divergencias_faixa_planilha': 0,
    }


def _normalizar_filtro_nm_seg(nm_seg: Optional[str]) -> Optional[str]:
    """Normaliza filtro de segmento (Varejo / Empresarial) vindo da query string."""
    if nm_seg in (None, '', '0', 0, 'todos', 'TODOS', 'Todos'):
        return None
    raw = str(nm_seg).strip()
    if not raw:
        return None
    lower = raw.casefold()
    if lower == 'varejo':
        return 'Varejo'
    if lower == 'empresarial':
        return 'Empresarial'
    return raw


def _listar_segmentos_dashboard_fpd(indicador: str) -> list[str]:
    """Valores distintos de ``nm_seg`` no universo ImportacaoFPD do indicador."""
    vals = (
        ImportacaoFPD.objects.filter(
            indicador=indicador,
            dt_venc_orig__isnull=False,
        )
        .exclude(nm_seg__isnull=True)
        .exclude(nm_seg='')
        .values_list('nm_seg', flat=True)
        .distinct()
        .order_by('nm_seg')
    )
    return [str(v).strip() for v in vals if v and str(v).strip()]


def _listar_vendedores_dashboard_fpd(indicador: str) -> list[dict[str, Any]]:
    """Vendedores do CRM com contrato linkado em ImportacaoFPD do indicador.

    ``nome`` = username (nickname operacional).
    """
    vend_ids = (
        ImportacaoFPD.objects.filter(
            indicador=indicador,
            dt_venc_orig__isnull=False,
            contrato_m10__vendedor_id__isnull=False,
        )
        .values_list('contrato_m10__vendedor_id', flat=True)
        .distinct()
    )
    usuarios = (
        ContratoM10.objects.filter(vendedor_id__in=vend_ids)
        .select_related('vendedor')
        .values(
            'vendedor_id',
            'vendedor__username',
        )
        .distinct()
    )
    out: list[dict[str, Any]] = []
    vistos: set[int] = set()
    for row in usuarios:
        vid = row['vendedor_id']
        if not vid or vid in vistos:
            continue
        vistos.add(vid)
        nick = (row.get('vendedor__username') or '').strip() or f'#{vid}'
        out.append({'id': vid, 'nome': nick})
    out.sort(key=lambda x: x['nome'].lower())
    return out


def listar_faltam_no_crm(
    *,
    indicador: Optional[str] = None,
    mes: Optional[str] = None,
    q: Optional[str] = None,
    apenas_abertas: bool = False,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Linhas da planilha FPD/SPD/TPD sem ContratoM10/Venda no CRM."""
    qs = ImportacaoFPD.objects.filter(match_status='FALTA_CRM').order_by(
        '-atualizada_em', 'nr_ordem'
    )

    if indicador:
        ind = str(indicador).strip().upper()
        if ind in ('FPD', 'SPD', 'TPD'):
            qs = qs.filter(indicador=ind)

    if mes:
        data_inicio, data_fim = mes_range(mes)
        qs = qs.filter(dt_venc_orig__gte=data_inicio, dt_venc_orig__lt=data_fim)

    if apenas_abertas:
        qs = qs.filter(ds_sit_fatura__iexact='ABERTA')

    if q:
        q_clean = str(q).strip()
        qs = qs.filter(
            Q(nr_ordem__icontains=q_clean)
            | Q(id_contrato__icontains=q_clean)
            | Q(nr_fatura__icontains=q_clean)
            | Q(cd_vendedor_original__icontains=q_clean)
            | Q(municipio__icontains=q_clean)
        )

    total = qs.count()
    page = max(1, int(page or 1))
    page_size = max(1, min(250, int(page_size or 100)))
    start = (page - 1) * page_size
    end = start + page_size
    rows = list(qs[start:end])

    itens = []
    for r in rows:
        itens.append({
            'id': r.id,
            'nr_ordem': r.nr_ordem,
            'indicador': r.indicador,
            'numero_fatura_m10': r.numero_fatura_m10,
            'id_contrato': r.id_contrato,
            'nr_fatura': r.nr_fatura,
            'ds_status_fatura': r.ds_status_fatura,
            'ds_sit_fatura': r.ds_sit_fatura,
            'faixa': r.faixa,
            'nr_dias_atraso': r.nr_dias_atraso,
            'dt_venc_orig': r.dt_venc_orig.isoformat() if r.dt_venc_orig else None,
            'dt_pagamento': r.dt_pagamento.isoformat() if r.dt_pagamento else None,
            'vl_fatura': str(r.vl_fatura) if r.vl_fatura is not None else '0',
            'municipio': r.municipio,
            'uf': r.uf,
            'cd_vendedor_original': r.cd_vendedor_original,
            'nm_pdv': r.nm_pdv,
            'nm_gc': r.nm_gc,
            'atualizada_em': r.atualizada_em.isoformat() if r.atualizada_em else None,
            'dica_match': (
                'Buscar venda pelo nr_ordem (O.S.) no CRM / OSAB; '
                'confirmar se a venda está INSTALADA e se a O.S. está preenchida.'
            ),
        })

    base_totais = ImportacaoFPD.objects.filter(match_status='FALTA_CRM')
    if mes:
        data_inicio, data_fim = mes_range(mes)
        base_totais = base_totais.filter(
            dt_venc_orig__gte=data_inicio, dt_venc_orig__lt=data_fim
        )
    totais_indicador = {
        row['indicador']: row['c']
        for row in base_totais.values('indicador').annotate(c=Count('id'))
    }

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size if total else 0,
        'totais_indicador': totais_indicador,
        'itens': itens,
    }


def sincronizar_faltantes(mes_yyyy_mm: str, user: Any) -> dict[str, Any]:
    """Cria ContratoM10 a partir de Vendas INSTALADAS do mês ainda sem contrato.

    Espelha a lógica de ``PopularSafraM10View``: garante SafraM10, cria faltantes
    e recalcula totais. Retorna contagens da operação.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para sincronizar faltantes no Qualidade.')

    data_inicio, data_fim = mes_range(mes_yyyy_mm)
    safra, safra_criada = SafraM10.objects.get_or_create(
        mes_referencia=data_inicio,
        defaults={
            'total_instalados': 0,
            'total_ativos': 0,
            'total_elegivel_bonus': 0,
            'valor_bonus_total': 0,
        },
    )

    vendas = (
        Venda.objects.filter(
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
            data_instalacao__isnull=False,
            ativo=True,
            status_esteira__nome__iexact='INSTALADA',
        )
        .order_by('data_criacao')
        .select_related('cliente', 'vendedor', 'status_esteira', 'plano')
    )

    contratos_criados = 0
    contratos_duplicados = 0

    for venda in vendas:
        numero_contrato = venda.ordem_servico or f'VENDA_{venda.id}'
        if venda.ordem_servico:
            contrato_existe = ContratoM10.objects.filter(ordem_servico=venda.ordem_servico).exists()
        else:
            contrato_existe = ContratoM10.objects.filter(numero_contrato=numero_contrato).exists()

        if contrato_existe:
            contratos_duplicados += 1
            continue

        ContratoM10.objects.create(
            safra=mes_yyyy_mm,
            venda=venda,
            numero_contrato=numero_contrato,
            ordem_servico=venda.ordem_servico,
            cliente_nome=venda.cliente.nome_razao_social if venda.cliente else 'N/D',
            cpf_cliente=venda.cliente.cpf_cnpj if venda.cliente else '',
            vendedor=venda.vendedor,
            data_instalacao=venda.data_instalacao,
            plano_original=venda.plano.nome if venda.plano else 'N/D',
            plano_atual=venda.plano.nome if venda.plano else 'N/D',
            valor_plano=venda.plano.valor if venda.plano else 0,
            status_contrato='ATIVO',
            observacao=f'Importado de Venda #{venda.id} (sincronizar faltantes)',
        )
        contratos_criados += 1
        try:
            contrato_novo = ContratoM10.objects.get(numero_contrato=numero_contrato)
            contrato_novo.criar_ou_atualizar_faturas()
        except Exception:
            logger.exception('Falha ao criar faturas no sync OS=%s', venda.ordem_servico)

    total_contratos_safra = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).count()
    total_ativos = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
        status_contrato='ATIVO',
    ).count()
    safra.total_instalados = total_contratos_safra
    safra.total_ativos = total_ativos
    safra.save(update_fields=['total_instalados', 'total_ativos', 'atualizado_em'])
    _recalcular_totais_safra(mes_yyyy_mm)

    logger.info(
        '[Qualidade] sincronizar_faltantes mes=%s user=%s criados=%s duplicados=%s',
        mes_yyyy_mm,
        getattr(user, 'id', None),
        contratos_criados,
        contratos_duplicados,
    )
    return {
        'mes': mes_yyyy_mm,
        'safra_id': safra.id,
        'safra_criada': safra_criada,
        'contratos_criados': contratos_criados,
        'contratos_duplicados': contratos_duplicados,
        'total_contratos_safra': total_contratos_safra,
        'total_ativos': total_ativos,
    }


def criar_contrato_orfao_fpd(
    *,
    ordem_servico: Optional[str] = None,
    id_contrato: Optional[str] = None,
    cliente_nome: Optional[str] = None,
    dt_vencimento: Optional[date] = None,
    valor_fatura: Optional[Any] = None,
    status_fatura: Optional[str] = None,
) -> ContratoM10:
    """Cria ContratoM10 mínimo a partir de linha FPD sem match no sistema.

    Órfãos não podem ser tratados (cobrança) até haver CPF/vínculo com cliente.
    ``data_instalacao`` usa o vencimento FPD (ou hoje) só como placeholder.
    """
    os_clean = (ordem_servico or '').strip() or None
    id_clean = (id_contrato or '').strip() or None
    numero = id_clean or os_clean
    if not numero:
        raise ValueError('Informe ordem_servico ou id_contrato para criar órfão FPD.')

    if os_clean and ContratoM10.objects.filter(ordem_servico=os_clean).exists():
        return ContratoM10.objects.get(ordem_servico=os_clean)
    if ContratoM10.objects.filter(numero_contrato=numero).exists():
        return ContratoM10.objects.get(numero_contrato=numero)

    data_inst = dt_vencimento or timezone.localdate()
    nome = (cliente_nome or '').strip() or 'A identificar'

    kwargs: dict[str, Any] = {
        'venda': None,
        'numero_contrato': numero,
        'ordem_servico': os_clean,
        'numero_contrato_definitivo': id_clean,
        'cliente_nome': nome,
        'cpf_cliente': '',
        'vendedor': None,
        'data_instalacao': data_inst,
        'plano_original': 'N/D',
        'plano_atual': 'N/D',
        'valor_plano': 0,
        'status_contrato': 'ATIVO',
        'data_vencimento_fpd': dt_vencimento,
        'status_fatura_fpd': status_fatura,
        'valor_fatura_fpd': valor_fatura,
        'observacao': 'Órfão FPD — aguardando vínculo/CPF para tratamento',
    }
    if _contrato_tem_campo('orfao'):
        kwargs['orfao'] = True

    contrato = ContratoM10.objects.create(**kwargs)
    logger.info(
        '[Qualidade] contrato órfão criado id=%s os=%s numero=%s',
        contrato.id,
        os_clean,
        numero,
    )
    return contrato


def enriquecer_contato_contrato(contrato: ContratoM10) -> dict[str, Any]:
    """Obtém telefone(s) da Venda e e-mail do Cliente vinculados ao contrato."""
    telefone1 = None
    telefone2 = None
    email = None

    venda = getattr(contrato, 'venda', None)
    if venda is not None:
        telefone1 = (venda.telefone1 or '').strip() or None
        telefone2 = (venda.telefone2 or '').strip() or None
        cliente = getattr(venda, 'cliente', None)
        if cliente is not None:
            email = (cliente.email or '').strip() or None

    if not email and venda is None and contrato.cpf_cliente:
        cliente_alt = Cliente.objects.filter(cpf_cnpj=contrato.cpf_cliente).first()
        if cliente_alt:
            email = (cliente_alt.email or '').strip() or None

    if _contrato_tem_campo('telefone') and not telefone1:
        telefone1 = (getattr(contrato, 'telefone', None) or '').strip() or None
    if _contrato_tem_campo('email') and not email:
        email = (getattr(contrato, 'email', None) or '').strip() or None

    return {
        'telefone': telefone1 or telefone2,
        'telefone1': telefone1,
        'telefone2': telefone2,
        'email': email,
    }


def atualizar_contato(
    contrato_id: int,
    telefone: Optional[str] = None,
    email: Optional[str] = None,
) -> dict[str, Any]:
    """Atualiza telefone na Venda e e-mail no Cliente (quando houver vínculo).

    Se o ContratoM10 ganhar campos próprios de contato, também os persiste.
    """
    try:
        contrato = ContratoM10.objects.select_related('venda', 'venda__cliente').get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    atualizado: dict[str, Any] = {
        'contrato_id': contrato.id,
        'telefone': None,
        'email': None,
        'venda_atualizada': False,
        'cliente_atualizado': False,
    }

    tel = (telefone or '').strip() or None
    mail = (email or '').strip() or None

    venda = contrato.venda
    if tel and venda:
        venda.telefone1 = tel
        venda.save(update_fields=['telefone1', 'data_ultima_alteracao'])
        atualizado['venda_atualizada'] = True
        atualizado['telefone'] = tel
    elif tel and _contrato_tem_campo('telefone'):
        setattr(contrato, 'telefone', tel)
        contrato.save(update_fields=['telefone', 'atualizado_em'])
        atualizado['telefone'] = tel

    cliente: Optional[Cliente] = venda.cliente if venda else None
    if mail and cliente:
        cliente.email = mail
        cliente.save(update_fields=['email'])
        atualizado['cliente_atualizado'] = True
        atualizado['email'] = mail
    elif mail and _contrato_tem_campo('email'):
        setattr(contrato, 'email', mail)
        contrato.save(update_fields=['email', 'atualizado_em'])
        atualizado['email'] = mail

    if not atualizado['telefone'] or not atualizado['email']:
        contato = enriquecer_contato_contrato(contrato)
        atualizado['telefone'] = atualizado['telefone'] or contato.get('telefone')
        atualizado['email'] = atualizado['email'] or contato.get('email')

    return atualizado


def montar_mensagem_cobranca_roteiro1(
    contrato: ContratoM10,
    fatura: FaturaM10,
    nome_parceiro: str = 'Record PAP',
    nome_atendente: str = '_________',
) -> str:
    """Monta texto do Roteiro 1 da Jornada de Cobrança (2ª via + barras + PIX)."""
    nome_cliente = (contrato.cliente_nome or 'cliente').strip()
    saudacao = _saudacao_periodo()
    codigo_barras = (fatura.codigo_barras or '').strip() or '(código de barras indisponível)'
    codigo_pix = (fatura.codigo_pix or '').strip() or '(PIX indisponível)'

    return (
        f'Olá, {saudacao} Sr(a). {nome_cliente}.\n'
        f'Me chamo {nome_atendente}, sou especialista de qualidade do ({nome_parceiro}), '
        f'parceiro Oficial da Nio Fibra.\n'
        f'Identificamos um valor pendente referente ao seu plano Nio Fibra. '
        f'Segue a 2ª via da sua fatura, juntamente com o código de barras e a chave PIX.\n'
        f'Cód. de Barras:\n{codigo_barras}\n'
        f'PIX (Pagamento Instantâneo):\n{codigo_pix}\n'
        f'Destinatário: CLIENT CO SERVIÇOS DE RED\n'
        f'Caso o pagamento já tenha sido realizado, pedimos desculpas pelo incomodo e por favor, '
        f'desconsidere esta mensagem.\n'
        f'Lembramos que a confirmação do pagamento pode levar até 5 dias úteis.\n'
        f'Para agilizar a atualização do sistema, se possível, pedimos a gentileza de compartilhar '
        f'o comprovante de pagamento.\n'
        f'Você também pode acompanhar sua conta e faturas através do app Nio.\n'
        f'Instale o aplicativo no seu aparelho celular:\n'
        f'Disponível para Android e iOS:\n'
        f'Google Play Store (Android) https://play.google.com/store/apps/details?id=br.com.niointernet.app\n'
        f'Apple Store (iOS)  https://apps.apple.com/br/app/nio-internet/id6746278488\n'
        f'Você ainda pode realizar contato pelos canais de comunicação oficiais da Nio:\n'
        f'SAC:0800 001 1000\n'
        f'WhatsApp: 21-3605-1000\n\n'
        f'Obrigado e tenha um {saudacao}!'
    )


def _registrar_historico_envio(
    *,
    contrato: ContratoM10,
    fatura: Optional[FaturaM10],
    canal: str,
    destinatario: str,
    mensagem: str,
    user: Any,
    sucesso: bool,
    erro: Optional[str] = None,
    origem: Optional[str] = None,
    template_nome: str = '',
    message_id: str = '',
    status_entrega: str = '',
    erro_codigo: str = '',
) -> None:
    if HistoricoEnvioQualidade is None:
        return
    # AUTO = job sem usuário; MANUAL = tela; SISTEMA = webhook/botões
    if origem:
        origem_eff = origem
    elif getattr(user, 'pk', None):
        origem_eff = 'MANUAL'
    else:
        origem_eff = 'AUTO'
    mid = (message_id or '')[:191]
    status_eff = (status_entrega or '').strip().upper()
    if not status_eff and canal == 'WHATSAPP':
        status_eff = 'ACEITO' if sucesso else 'FALHOU'
    try:
        HistoricoEnvioQualidade.objects.create(
            contrato=contrato,
            fatura=fatura,
            canal=canal,
            origem=origem_eff,
            template_nome=(template_nome or '')[:120],
            destinatario=destinatario,
            mensagem=mensagem,
            enviado_por=user if getattr(user, 'pk', None) else None,
            sucesso=sucesso,
            erro=erro or '',
            message_id=mid,
            status_entrega=status_eff,
            erro_codigo=(erro_codigo or '')[:32],
            status_atualizado_em=timezone.now() if status_eff else None,
        )
    except Exception:
        logger.exception('[Qualidade] Falha ao registrar HistoricoEnvioQualidade')


def _digitos_telefone_variantes(telefone: str) -> set[str]:
    digitos_set: set[str] = set()
    d = re.sub(r'\D', '', str(telefone or ''))
    if not d:
        return digitos_set
    digitos_set.add(d)
    if d.startswith('55') and len(d) > 11:
        digitos_set.add(d[2:])
    elif not d.startswith('55') and len(d) >= 10:
        digitos_set.add('55' + d)
    return digitos_set


def resolver_contexto_cobranca_por_telefone(
    telefone: str,
    *,
    dias: int = 14,
) -> Optional[dict[str, Any]]:
    """
    Acha contrato/fatura a partir de envio WhatsApp recente de cobrança
    (mesmo critério do webhook dos botões Meta).
    """
    if HistoricoEnvioQualidade is None:
        return None
    digitos_set = _digitos_telefone_variantes(telefone)
    if not digitos_set:
        return None
    limite = timezone.now() - relativedelta(days=max(1, int(dias)))
    hist = (
        HistoricoEnvioQualidade.objects.filter(
            canal='WHATSAPP',
            sucesso=True,
            criado_em__gte=limite,
            fatura_id__isnull=False,
        )
        .select_related('fatura', 'contrato')
        .order_by('-criado_em')[:60]
    )
    for h in hist:
        dest = re.sub(r'\D', '', str(h.destinatario or ''))
        if not dest:
            continue
        if dest in digitos_set or any(
            dest.endswith(d[-11:]) for d in digitos_set if len(d) >= 11
        ):
            return {
                'contrato': h.contrato,
                'fatura': h.fatura,
                'historico_envio': h,
            }
    return None


def registrar_resposta_cliente_qualidade(
    *,
    contrato: ContratoM10,
    fatura: Optional[FaturaM10],
    telefone: str,
    texto: str,
    origem: str = 'texto',
) -> Optional[Any]:
    """Persiste clique de botão ou texto livre do cliente após cobrança."""
    if HistoricoEnvioQualidade is None:
        return None
    msg = (texto or '').strip()
    if not msg:
        return None
    prefixo = 'Botão: ' if origem == 'botao' else 'Texto: '
    try:
        return HistoricoEnvioQualidade.objects.create(
            contrato=contrato,
            fatura=fatura,
            canal='RESPOSTA',
            origem='SISTEMA',
            destinatario=(telefone or '')[:255] or '—',
            mensagem=(prefixo + msg)[:5000],
            enviado_por=None,
            sucesso=True,
        )
    except Exception:
        logger.exception('[Qualidade] Falha ao registrar resposta do cliente')
        return None


def listar_historico_contato_contrato(contrato_id: int, *, limite: int = 80) -> dict[str, Any]:
    """Timeline de envios e respostas do contrato para o modal da Qualidade."""
    try:
        contrato = ContratoM10.objects.select_related('venda').get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    itens: list[dict[str, Any]] = []
    if HistoricoEnvioQualidade is not None:
        qs = (
            HistoricoEnvioQualidade.objects.filter(contrato_id=contrato_id)
            .select_related('enviado_por', 'fatura')
            .order_by('-criado_em')[: max(1, min(200, limite))]
        )
        for h in qs:
            itens.append({
                'id': h.id,
                'canal': h.canal,
                'destinatario': h.destinatario,
                'mensagem': h.mensagem or '',
                'sucesso': bool(h.sucesso),
                'erro': h.erro or '',
                'message_id': h.message_id or '',
                'status_entrega': h.status_entrega or '',
                'erro_codigo': h.erro_codigo or '',
                'criado_em': _iso_dt_local(h.criado_em),
                'enviado_por': (
                    (h.enviado_por.get_full_name() or h.enviado_por.username)
                    if h.enviado_por_id
                    else None
                ),
                'fatura_id': h.fatura_id,
            })

    return {
        'contrato_id': contrato.id,
        'cliente_nome': contrato.cliente_nome or '',
        'cpf_cliente': (contrato.cpf_cliente or '').strip(),
        'ordem_servico': contrato.ordem_servico or '',
        'id_contrato': _id_contrato_fpd(contrato),
        'itens': itens,
    }


def registrar_ligacao_qualidade(
    contrato_id: int,
    user: Any,
    *,
    destino: str = '',
    sucesso: bool = True,
    detalhe: str = '',
) -> dict[str, Any]:
    """Espelha ligação iniciada na Qualidade no HistoricoEnvioQualidade."""
    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    telefone = (destino or '').strip()
    if not telefone:
        contato = enriquecer_contato_contrato(contrato)
        telefone = (contato.get('telefone') or contato.get('telefone1') or '').strip() or '—'

    _registrar_historico_envio(
        contrato=contrato,
        fatura=None,
        canal='LIGACAO',
        destinatario=telefone,
        mensagem=(detalhe or 'Ligação iniciada pela Qualidade')[:2000],
        user=user,
        sucesso=sucesso,
        erro=None if sucesso else (detalhe or 'Falha na ligação'),
    )
    return {'ok': True, 'contrato_id': contrato_id, 'destino': telefone}


def escolher_template_fatura_cobranca(
    fatura: Any,
    *,
    modo: str = 'auto',
    hoje: Optional[date] = None,
) -> tuple[str, bool]:
    """Escolhe o template Meta e se inclui {{6}} (dias de atraso).

    modo:
      reducao_sinal — tela Qualidade (envio manual e lote da aba Tratamento)
      template | auto — job D−5 / D+5 / recorrente
    """
    from crm_app.services.whatsapp.nio_templates import (
        TEMPLATE_FATURA_LEMBRETE_5D,
        TEMPLATE_FATURA_RECORRENTE,
        TEMPLATE_FATURA_REDUCAO_SINAL,
        TEMPLATE_FATURA_VENCIDA_5D,
    )

    modo_eff = (modo or 'auto').strip().lower()
    if modo_eff in ('reducao', 'reducao_sinal'):
        return TEMPLATE_FATURA_REDUCAO_SINAL, False

    ref = hoje or timezone.localdate()
    venc = getattr(fatura, 'data_vencimento', None)
    if venc is None:
        return TEMPLATE_FATURA_RECORRENTE, True
    dias_ate = (venc - ref).days
    dias_atraso = (ref - venc).days
    if dias_ate >= 0:
        return TEMPLATE_FATURA_LEMBRETE_5D, False
    if dias_atraso <= 7:
        return TEMPLATE_FATURA_VENCIDA_5D, False
    return TEMPLATE_FATURA_RECORRENTE, True


def extrair_data_promessa_texto(
    texto: str,
    *,
    hoje: Optional[date] = None,
) -> Optional[date]:
    """Interpreta mensagem só com data (DD/MM ou DD/MM/AAAA) como previsão de pagamento."""
    raw = (texto or '').strip()
    match = re.fullmatch(
        r'(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?',
        raw,
    )
    if not match:
        return None
    dia = int(match.group(1))
    mes = int(match.group(2))
    ref = hoje or timezone.localdate()
    ano_txt = match.group(3)
    if ano_txt:
        ano = int(ano_txt)
        if ano < 100:
            ano += 2000
    else:
        ano = ref.year
    try:
        prevista = date(ano, mes, dia)
    except ValueError:
        return None
    if not ano_txt and prevista < ref:
        try:
            prevista = date(ano + 1, mes, dia)
        except ValueError:
            return None
    if prevista < ref:
        return None
    if prevista > ref + timedelta(days=120):
        return None
    return prevista


def gravar_promessa_pagamento_qualidade(
    fatura: FaturaM10,
    data_promessa: date,
    *,
    contrato: Optional[ContratoM10] = None,
    telefone: str = '',
) -> bool:
    """Grava data de promessa na fatura e registra no histórico da Qualidade."""
    try:
        fatura.data_promessa_pagamento = data_promessa
        fatura.save(update_fields=['data_promessa_pagamento'])
    except Exception:
        logger.exception('[Qualidade] Falha ao gravar promessa fatura=%s', getattr(fatura, 'id', None))
        return False
    registrar_resposta_cliente_qualidade(
        contrato=contrato or fatura.contrato,
        fatura=fatura,
        telefone=telefone,
        texto=f'Promessa de pagamento: {data_promessa.strftime("%d/%m/%Y")}',
        origem='texto',
    )
    return True


def enviar_cobranca_whatsapp(
    contrato_id: int,
    fatura_id: int,
    user: Any,
    telefone_override: Optional[str] = None,
    *,
    modo: str = "auto",
) -> dict[str, Any]:
    """
    Envia cobrança via WhatsApp.

    modo:
      - auto: template Meta se habilitado; senão Roteiro 1 (PIX/barras)
      - template: só template (lembrete/vencida/recorrente conforme dias) — job 09:00
      - reducao_sinal: nio_fatura_reducao_sinal_v1 (tela Qualidade)
      - roteiro1: texto completo com 2ª via (janela 24h / após botão)
    """
    try:
        contrato = ContratoM10.objects.select_related('venda', 'venda__cliente', 'vendedor').get(
            pk=contrato_id
        )
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    if not pode_tratar_contrato(contrato):
        return {
            'ok': False,
            'erro': 'Contrato órfão ou sem CPF — tratamento bloqueado até vínculo.',
        }

    try:
        fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
    except FaturaM10.DoesNotExist as exc:
        raise ValueError(f'Fatura {fatura_id} não encontrada para o contrato.') from exc

    ok_dados, erro_dados = validar_fatura_para_envio_cobranca(fatura)
    if not ok_dados:
        return {'ok': False, 'erro': erro_dados, 'fatura_id': fatura.id}

    contato = enriquecer_contato_contrato(contrato)
    telefone = (telefone_override or '').strip() or contato.get('telefone')
    if not telefone:
        _registrar_historico_envio(
            contrato=contrato,
            fatura=fatura,
            canal='WHATSAPP',
            destinatario='—',
            mensagem='Telefone não informado',
            user=user,
            sucesso=False,
            erro='Telefone não informado. Informe e grave o contato do cliente.',
        )
        return {'ok': False, 'erro': 'Telefone não informado. Informe e grave o contato do cliente.'}

    if telefone_override:
        atualizar_contato(contrato.id, telefone=telefone_override)

    nome_atendente = ''
    if user is not None:
        nome_atendente = (
            getattr(user, 'first_name', None)
            or getattr(user, 'username', None)
            or '_________'
        )
    mensagem = montar_mensagem_cobranca_roteiro1(
        contrato,
        fatura,
        nome_atendente=nome_atendente or '_________',
    )

    from crm_app.services.whatsapp.nio_templates import (
        TEMPLATE_FATURA_REDUCAO_SINAL,
        enviar_template_fatura,
        montar_fallback_fatura_reducao_sinal,
        templates_habilitados,
    )

    modo_eff = (modo or 'auto').strip().lower()
    if modo_eff in ('reducao', 'reducao_sinal'):
        modo_eff = 'reducao_sinal'
    usar_template = modo_eff in ('template', 'reducao_sinal') or (
        modo_eff == 'auto' and templates_habilitados()
    )

    canal = 'roteiro1'
    template_usado = ''
    ok = False
    resp: Any = None
    try:
        if usar_template and modo_eff != 'roteiro1':
            nome_cli = (contrato.cliente_nome or 'Cliente').strip()
            tpl, incluir_atraso = escolher_template_fatura_cobranca(
                fatura, modo=modo_eff
            )
            template_usado = tpl
            fallback = mensagem
            if tpl == TEMPLATE_FATURA_REDUCAO_SINAL:
                fallback = montar_fallback_fatura_reducao_sinal(nome_cli, fatura)
            ok, resp, canal = enviar_template_fatura(
                telefone,
                tpl,
                nome_cli,
                fatura,
                fallback_texto=fallback,
                incluir_dias_atraso=incluir_atraso,
            )
        else:
            ok, resp = WhatsAppService.para_cliente().enviar_mensagem_texto(
                telefone, mensagem, variar=False
            )
            canal = 'roteiro1'
    except Exception as exc:
        logger.exception('[Qualidade] Erro WhatsApp contrato=%s', contrato_id)
        _registrar_historico_envio(
            contrato=contrato,
            fatura=fatura,
            canal='WHATSAPP',
            destinatario=telefone,
            mensagem=mensagem,
            user=user,
            sucesso=False,
            erro=str(exc),
            template_nome=template_usado,
            status_entrega='FALHOU',
        )
        return {'ok': False, 'erro': str(exc)}

    from crm_app.services.whatsapp.status_entrega_service import (
        extrair_erro_meta,
        extrair_message_id_resposta,
    )

    message_id = extrair_message_id_resposta(resp)
    erro_codigo, erro_meta = extrair_erro_meta(resp)
    erro_txt = None if ok else (erro_meta or str(resp) if resp else 'Falha no envio WhatsApp')
    _registrar_historico_envio(
        contrato=contrato,
        fatura=fatura,
        canal='WHATSAPP',
        destinatario=telefone,
        mensagem=f'[{canal}] {mensagem[:500]}',
        user=user,
        sucesso=bool(ok),
        erro=erro_txt,
        template_nome=template_usado or (canal if canal != 'roteiro1' else ''),
        message_id=message_id,
        status_entrega='ACEITO' if ok else 'FALHOU',
        erro_codigo=erro_codigo,
    )
    return {
        'ok': bool(ok),
        'telefone': telefone,
        'fatura_id': fatura.id,
        'mensagem': mensagem,
        'canal': canal,
        'template_nome': template_usado,
        'message_id': message_id or None,
        'status_entrega': 'ACEITO' if ok else 'FALHOU',
        'erro_codigo': erro_codigo or None,
        'resposta': resp,
        'detail': (
            (
                f'Cobrança enviada via {canal}'
                + (f' ({template_usado}).' if template_usado else '.')
                + ' Aguardando confirmação de entrega da Meta.'
            )
            if ok
            else None
        ),
        'erro': None if ok else (erro_txt or 'Falha no envio WhatsApp'),
    }


def enviar_cobranca_email(
    contrato_id: int,
    fatura_id: int,
    user: Any,
    email_override: Optional[str] = None,
) -> dict[str, Any]:
    """Envia cobrança Roteiro 1 por e-mail. Bloqueia órfão ou sem CPF."""
    try:
        contrato = ContratoM10.objects.select_related('venda', 'venda__cliente', 'vendedor').get(
            pk=contrato_id
        )
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    if not pode_tratar_contrato(contrato):
        return {
            'ok': False,
            'erro': 'Contrato órfão ou sem CPF — tratamento bloqueado até vínculo.',
        }

    try:
        fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
    except FaturaM10.DoesNotExist as exc:
        raise ValueError(f'Fatura {fatura_id} não encontrada para o contrato.') from exc

    ok_dados, erro_dados = validar_fatura_para_envio_cobranca(fatura)
    if not ok_dados:
        return {'ok': False, 'erro': erro_dados, 'fatura_id': fatura.id}

    contato = enriquecer_contato_contrato(contrato)
    destino = (email_override or '').strip() or contato.get('email')
    if not destino:
        return {'ok': False, 'erro': 'E-mail não informado. Informe e grave o contato do cliente.'}

    if email_override:
        atualizar_contato(contrato.id, email=email_override)

    nome_atendente = ''
    if user is not None:
        nome_atendente = (
            getattr(user, 'first_name', None)
            or getattr(user, 'username', None)
            or '_________'
        )
    mensagem = montar_mensagem_cobranca_roteiro1(
        contrato,
        fatura,
        nome_atendente=nome_atendente or '_________',
    )
    assunto = f'2ª via da fatura Nio Fibra — {contrato.cliente_nome or "cliente"}'
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(
        settings, 'EMAIL_HOST_USER', None
    )
    if not from_email:
        return {'ok': False, 'erro': 'Remetente de e-mail não configurado (DEFAULT_FROM_EMAIL).'}

    try:
        msg = EmailMultiAlternatives(
            subject=assunto,
            body=mensagem,
            from_email=from_email,
            to=[destino],
        )
        msg.attach_alternative(f'<pre style="font-family:sans-serif">{mensagem}</pre>', 'text/html')
        msg.send(fail_silently=False)
        ok = True
        erro = None
    except Exception as exc:
        logger.exception('[Qualidade] Erro e-mail contrato=%s', contrato_id)
        ok = False
        erro = str(exc)

    _registrar_historico_envio(
        contrato=contrato,
        fatura=fatura,
        canal='EMAIL',
        destinatario=destino,
        mensagem=mensagem,
        user=user,
        sucesso=ok,
        erro=erro,
    )
    return {
        'ok': ok,
        'email': destino,
        'fatura_id': fatura.id,
        'mensagem': mensagem,
        'erro': erro,
    }


STATUS_FATURA_EDITAVEIS: list[str] = ['PAGO', 'NAO_PAGO', 'AGUARDANDO', 'ATRASADO', 'OUTROS']


def limpar_conferencia_fpd_fatura(fatura_id: int, user: Any) -> dict[str, Any]:
    """Remove marcação de conferência FPD (ex.: Aguard. FPD) de uma fatura.

    Usado quando o BO desfaz um teste ou cancela a pendência de confirmação
    na planilha. Mantém o status operacional atual da fatura.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para limpar conferência FPD.')

    try:
        fatura = FaturaM10.objects.select_related('contrato').get(pk=fatura_id)
    except FaturaM10.DoesNotExist as exc:
        raise ValueError(f'Fatura {fatura_id} não encontrada.') from exc

    conf_antes = (fatura.conferencia_fpd or '').strip().upper()
    if not conf_antes:
        return {
            'ok': True,
            'fatura_id': fatura.id,
            'contrato_id': fatura.contrato_id,
            'conferencia_fpd': '',
            'alterado': False,
            'detalhe': detalhe_contrato_faturas(fatura.contrato_id),
        }

    fatura.conferencia_fpd = ''
    fatura.status_informado_tratamento = ''
    fatura.data_status_tratamento = None
    fatura.status_origem = 'SISTEMA'
    fatura.save(update_fields=[
        'conferencia_fpd',
        'status_informado_tratamento',
        'data_status_tratamento',
        'status_origem',
        'atualizado_em',
    ])

    logger.info(
        '[Qualidade] limpar_conferencia_fpd fatura=%s conf_antes=%s user=%s',
        fatura_id,
        conf_antes,
        getattr(user, 'id', None),
    )
    return {
        'ok': True,
        'fatura_id': fatura.id,
        'contrato_id': fatura.contrato_id,
        'conferencia_fpd': '',
        'alterado': True,
        'detalhe': detalhe_contrato_faturas(fatura.contrato_id),
    }


def _valor_referencia_faturas(contrato: ContratoM10) -> float:
    """Valor padrão das faturas: GDP da venda → valor_plano → valor FPD.

    Prioriza o preço GDP (mesma fonte do comercial) para manter as 10 faturas
    alinhadas ao plano; cai no cadastro do contrato / FPD se o GDP falhar.
    """
    valor = 0.0
    venda = getattr(contrato, 'venda', None)
    if venda is not None and getattr(venda, 'plano_id', None):
        try:
            from crm_app.services.gdp_preco_service import resolver_valor_plano_venda

            valor_gdp, _meta = resolver_valor_plano_venda(venda)
            if valor_gdp is not None and float(valor_gdp) > 0:
                valor = float(valor_gdp)
        except Exception:
            logger.exception(
                '[Qualidade] Falha ao resolver valor GDP contrato=%s', contrato.pk
            )
    if valor <= 0 and contrato.valor_plano:
        valor = float(contrato.valor_plano)
    if valor <= 0 and contrato.valor_fatura_fpd:
        valor = float(contrato.valor_fatura_fpd)
    return valor


def detalhe_contrato_faturas(contrato_id: int) -> dict[str, Any]:
    """Retorna contrato + até 10 faturas para o painel de edição do BO."""
    try:
        contrato = ContratoM10.objects.select_related(
            'vendedor',
            'venda',
            'venda__cliente',
            'venda__plano',
            'venda__forma_pagamento',
        ).get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    valor_ref = _valor_referencia_faturas(contrato)

    # Garante esqueleto 1–10 criando só as faltantes (não sobrescreve datas já editadas)
    existentes = set(
        contrato.faturas.values_list('numero_fatura', flat=True)
    )
    if contrato.data_instalacao and len(existentes) < 10:
        for i in range(1, 11):
            if i in existentes:
                continue
            try:
                FaturaM10.objects.create(
                    contrato=contrato,
                    numero_fatura=i,
                    data_vencimento=contrato.calcular_vencimento_fatura_n(i),
                    data_disponibilidade=contrato.calcular_data_disponibilidade(i),
                    valor=valor_ref,
                    status='NAO_PAGO',
                )
            except Exception:
                logger.exception(
                    '[Qualidade] Falha ao criar fatura %s contrato=%s', i, contrato_id
                )

    # Faturas zeradas herdam o valor do plano/GDP (meses preenchidos sem valor)
    if valor_ref > 0:
        contrato.faturas.filter(Q(valor__isnull=True) | Q(valor=0)).update(
            valor=valor_ref,
            atualizado_em=timezone.now(),
        )

    # Mais atrasada (vencimento mais antigo) → vencimento mais recente
    faturas_qs = contrato.faturas.all().order_by(
        F('data_vencimento').asc(nulls_last=True),
        'numero_fatura',
    )
    faturas: list[dict[str, Any]] = []
    pagas = 0
    f1: Optional[FaturaM10] = None
    for f in faturas_qs:
        if f.numero_fatura == 1:
            f1 = f
        if _fatura_esta_fechada(f.status):
            pagas += 1
        tem_pdf = bool(f.arquivo_pdf) or bool(f.pdf_url)
        indicador = NUMERO_FATURA_PARA_INDICADOR.get(f.numero_fatura, '')
        faturas.append({
            'id': f.id,
            'numero_fatura': f.numero_fatura,
            'indicador': indicador,
            'status': f.status,
            'status_display': f.get_status_display(),
            'status_origem': f.status_origem or '',
            'conferencia_fpd': f.conferencia_fpd or '',
            'status_informado_tratamento': f.status_informado_tratamento or '',
            'ds_status_fatura_fpd': f.ds_status_fatura_fpd or '',
            'fechada': _fatura_esta_fechada(f.status),
            'data_vencimento': f.data_vencimento.isoformat() if f.data_vencimento else '',
            'data_pagamento': f.data_pagamento.isoformat() if f.data_pagamento else '',
            'data_promessa_pagamento': (
                f.data_promessa_pagamento.isoformat() if f.data_promessa_pagamento else ''
            ),
            'valor': float(f.valor) if f.valor is not None else 0,
            'codigo_pix': f.codigo_pix or '',
            'codigo_barras': f.codigo_barras or '',
            'tem_pdf': tem_pdf,
            'pdf_url': f.pdf_url or '',
            'download_url': f'/api/qualidade/faturas/{f.id}/pdf/' if tem_pdf else '',
        })

    total = len(faturas)
    elegivel = _contrato_elegivel_dinamico(contrato)
    return {
        'id': contrato.id,
        'ordem_servico': contrato.ordem_servico or '-',
        'id_contrato': _id_contrato_fpd(contrato, f1),
        'cliente_nome': contrato.cliente_nome,
        'cpf_cliente': contrato.cpf_cliente or '',
        'vendedor_nome': _vendedor_nome(contrato),
        'status_contrato': contrato.status_contrato,
        'orfao': _eh_orfao(contrato),
        'pode_tratar': pode_tratar_contrato(contrato),
        'faturas_pagas': pagas,
        'total_faturas': total,
        'elegivel': elegivel,
        'faturas': faturas,
        'status_choices': [
            {'value': v, 'label': lbl} for v, lbl in FaturaM10.STATUS_CHOICES
        ],
    }


def salvar_faturas_contrato(
    contrato_id: int,
    faturas_payload: list[dict[str, Any]],
    user: Any,
) -> dict[str, Any]:
    """Atualiza status, valor, vencimento, pagamento, PIX e código de barras em lote.

    Recalcula elegibilidade ao final.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para editar faturas no Qualidade.')

    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    atualizadas = 0
    erros: list[str] = []

    for item in faturas_payload or []:
        fatura_id = item.get('id')
        if not fatura_id:
            continue
        try:
            fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
        except FaturaM10.DoesNotExist:
            erros.append(f'Fatura {fatura_id} não pertence ao contrato.')
            continue

        campos: list[str] = []
        status_mudou = False
        if 'status' in item and item['status']:
            st = str(item['status']).upper()
            if st in STATUS_FATURA_EDITAVEIS:
                if fatura.status != st:
                    status_mudou = True
                fatura.status = st
                campos.append('status')
            else:
                erros.append(f'Status inválido na fatura {fatura.numero_fatura}: {st}')

        if 'valor' in item and item['valor'] is not None and item['valor'] != '':
            try:
                fatura.valor = float(str(item['valor']).replace(',', '.'))
                campos.append('valor')
            except (TypeError, ValueError):
                erros.append(f'Valor inválido na fatura {fatura.numero_fatura}')

        if 'data_vencimento' in item:
            raw = item.get('data_vencimento') or None
            if raw:
                try:
                    fatura.data_vencimento = date.fromisoformat(str(raw)[:10])
                    campos.append('data_vencimento')
                except ValueError:
                    erros.append(f'Vencimento inválido na fatura {fatura.numero_fatura}')

        if 'data_pagamento' in item:
            raw = item.get('data_pagamento') or None
            if raw:
                try:
                    fatura.data_pagamento = date.fromisoformat(str(raw)[:10])
                    campos.append('data_pagamento')
                except ValueError:
                    erros.append(f'Pagamento inválido na fatura {fatura.numero_fatura}')
            elif raw == '' or raw is None:
                if fatura.data_pagamento is not None:
                    fatura.data_pagamento = None
                    campos.append('data_pagamento')

        if 'data_promessa_pagamento' in item:
            raw = item.get('data_promessa_pagamento') or None
            if raw:
                try:
                    fatura.data_promessa_pagamento = date.fromisoformat(str(raw)[:10])
                    campos.append('data_promessa_pagamento')
                except ValueError:
                    erros.append(f'Promessa inválida na fatura {fatura.numero_fatura}')
            else:
                if fatura.data_promessa_pagamento is not None:
                    fatura.data_promessa_pagamento = None
                    campos.append('data_promessa_pagamento')

        if 'codigo_pix' in item:
            fatura.codigo_pix = (item.get('codigo_pix') or '').strip() or None
            campos.append('codigo_pix')

        if 'codigo_barras' in item:
            fatura.codigo_barras = (item.get('codigo_barras') or '').strip() or None
            campos.append('codigo_barras')

        # Se marcou PAGO e não tem data_pagamento, usa hoje
        if fatura.status == 'PAGO' and not fatura.data_pagamento:
            fatura.data_pagamento = timezone.localdate()
            if 'data_pagamento' not in campos:
                campos.append('data_pagamento')

        # Status alterado no tratamento → aguarda confirmação na próxima importação FPD
        if status_mudou:
            fatura.status_origem = 'TRATAMENTO'
            fatura.conferencia_fpd = 'AGUARDANDO'
            fatura.status_informado_tratamento = fatura.status
            fatura.data_status_tratamento = timezone.now()
            campos.extend([
                'status_origem',
                'conferencia_fpd',
                'status_informado_tratamento',
                'data_status_tratamento',
            ])

        if campos:
            campos.append('atualizado_em')
            fatura.save(update_fields=list(dict.fromkeys(campos)))
            atualizadas += 1

            # Espelha datas/valor da fatura 1; status_fatura_fpd fica só com a planilha
            if fatura.numero_fatura == 1:
                contrato.data_vencimento_fpd = fatura.data_vencimento
                contrato.data_pagamento_fpd = fatura.data_pagamento
                contrato.valor_fatura_fpd = fatura.valor
                contrato.save(update_fields=[
                    'data_vencimento_fpd', 'data_pagamento_fpd',
                    'valor_fatura_fpd', 'atualizado_em',
                ])
                # Valor informado na 1ª fatura alinha as demais ainda zeradas
                if fatura.valor is not None and float(fatura.valor) > 0:
                    contrato.faturas.filter(
                        Q(valor__isnull=True) | Q(valor=0)
                    ).exclude(pk=fatura.pk).update(
                        valor=fatura.valor,
                        atualizado_em=timezone.now(),
                    )

    elegivel = contrato.calcular_elegibilidade()
    if contrato.safra:
        _recalcular_totais_safra(contrato.safra)

    logger.info(
        '[Qualidade] salvar_faturas contrato=%s user=%s atualizadas=%s elegivel=%s',
        contrato_id,
        getattr(user, 'id', None),
        atualizadas,
        elegivel,
    )
    return {
        'ok': True,
        'atualizadas': atualizadas,
        'elegivel': elegivel,
        'erros': erros,
        'detalhe': detalhe_contrato_faturas(contrato_id),
    }


def _parse_data_nio(raw: Any) -> Optional[date]:
    """Normaliza due_date_raw / data_vencimento vindos da API Nio."""
    if not raw:
        return None
    if hasattr(raw, 'strftime'):
        return raw  # type: ignore[return-value]
    if isinstance(raw, str) and len(raw) >= 8:
        try:
            from datetime import datetime as dt
            s = raw[:10].replace('/', '-')
            if '-' in s and len(s) >= 10:
                return dt.strptime(s[:10], '%Y-%m-%d').date()
            digits = re.sub(r'\D', '', raw)[:8]
            if len(digits) == 8:
                return dt.strptime(digits, '%Y%m%d').date()
        except Exception:
            return None
    return None


def _mes_ref_yyyy_mm(d: Optional[date], reference_month: Any = None) -> str:
    if d:
        return d.strftime('%Y-%m')
    ref = str(reference_month or '').strip()
    if len(ref) == 6 and ref.isdigit():
        return f'{ref[:4]}-{ref[4:6]}'
    if len(ref) == 7 and ref[4] == '-':
        return ref
    return ''


def buscar_opcoes_nio_fatura(
    contrato_id: int,
    numero_fatura: int,
    user: Any,
) -> dict[str, Any]:
    """Consulta a Nio e devolve todas as opções para o BO escolher.

    Destaca as que batem com o mês da fatura local (vencimento ou referência).
    Não vincula automaticamente — o usuário precisa aceitar.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para buscar na Nio.')

    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    cpf = re.sub(r'\D', '', (contrato.cpf_cliente or ''))
    if len(cpf) < 11:
        raise ValueError('CPF do cliente ausente ou inválido — não é possível buscar na Nio.')

    fatura = FaturaM10.objects.filter(contrato=contrato, numero_fatura=numero_fatura).first()
    if not fatura:
        raise ValueError(f'Fatura {numero_fatura} não encontrada neste contrato.')

    venc_local = fatura.data_vencimento or contrato.calcular_vencimento_fatura_n(numero_fatura)
    mes_alvo = _mes_ref_yyyy_mm(venc_local)

    from crm_app.nio_api import consultar_dividas_nio

    api_result = consultar_dividas_nio(cpf, offset=0, limit=50, headless=True)
    invoices = api_result.get('invoices') or []

    opcoes: list[dict[str, Any]] = []
    for idx, inv in enumerate(invoices):
        dv = _parse_data_nio(inv.get('due_date_raw') or inv.get('data_vencimento'))
        mes_nio = _mes_ref_yyyy_mm(dv, inv.get('reference_month'))
        match_mes = bool(mes_alvo and mes_nio and mes_alvo == mes_nio)
        diff_dias = abs((dv - venc_local).days) if dv and venc_local else None
        opcoes.append({
            'opcao_id': idx,
            'valor': inv.get('amount'),
            'data_vencimento': dv.isoformat() if dv else '',
            'data_vencimento_display': dv.strftime('%d/%m/%Y') if dv else '—',
            'mes_referencia': mes_nio,
            'codigo_pix': inv.get('pix') or inv.get('codigo_pix') or '',
            'codigo_barras': inv.get('barcode') or inv.get('codigo_barras') or '',
            'status_nio': inv.get('status') or '',
            'product': inv.get('product') or '',
            'match_mes': match_mes,
            'diff_dias_vencimento': diff_dias,
            'recomendado': match_mes or (diff_dias is not None and diff_dias <= 3),
            # IDs internos para buscar PDF no aceite
            'debt_id': inv.get('debt_id') or '',
            'invoice_id': str(inv.get('invoice_id') or ''),
            'reference_month_raw': inv.get('reference_month') or '',
        })

    # Recomendadas primeiro
    opcoes.sort(key=lambda o: (not o['recomendado'], o.get('diff_dias_vencimento') is None, o.get('diff_dias_vencimento') or 999))

    return {
        'ok': True,
        'contrato_id': contrato.id,
        'numero_fatura': numero_fatura,
        'fatura_id': fatura.id,
        'cpf': cpf,
        'mes_alvo': mes_alvo,
        'vencimento_local': venc_local.isoformat() if venc_local else '',
        'vencimento_local_display': venc_local.strftime('%d/%m/%Y') if venc_local else '—',
        'sem_dividas': len(opcoes) == 0,
        'mensagem': 'CPF sem dívidas no momento.' if not opcoes else '',
        'opcoes': opcoes,
        'token': api_result.get('token') or '',
        'api_base': api_result.get('api_base') or '',
        'session_id': api_result.get('session_id') or '',
    }


def aplicar_opcao_nio_fatura(
    contrato_id: int,
    fatura_id: int,
    opcao: dict[str, Any],
    user: Any,
    *,
    token: str = '',
    api_base: str = '',
    session_id: str = '',
    cpf: str = '',
) -> dict[str, Any]:
    """Vincula valor, vencimento, PIX, barras e PDF da opção Nio aceita pelo BO."""
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para aplicar dados da Nio.')

    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
        fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
    except (ContratoM10.DoesNotExist, FaturaM10.DoesNotExist) as exc:
        raise ValueError('Contrato/fatura não encontrados.') from exc

    campos: list[str] = []

    if opcao.get('valor') not in (None, ''):
        try:
            fatura.valor = float(str(opcao['valor']).replace(',', '.'))
            campos.append('valor')
        except (TypeError, ValueError):
            pass

    dv = opcao.get('data_vencimento')
    if dv:
        try:
            fatura.data_vencimento = date.fromisoformat(str(dv)[:10])
            campos.append('data_vencimento')
        except ValueError:
            pass

    if opcao.get('codigo_pix'):
        fatura.codigo_pix = str(opcao['codigo_pix']).strip()
        campos.append('codigo_pix')
    if opcao.get('codigo_barras'):
        fatura.codigo_barras = str(opcao['codigo_barras']).strip()
        campos.append('codigo_barras')

    # PDF sob demanda no aceite
    pdf_url = opcao.get('pdf_url') or ''
    if not pdf_url and token and api_base and session_id and opcao.get('invoice_id'):
        try:
            import requests
            from crm_app.nio_api import get_invoice_pdf_url

            cpf_limpo = re.sub(r'\D', '', cpf or contrato.cpf_cliente or '')
            sess = requests.Session()
            pdf_url = get_invoice_pdf_url(
                api_base,
                token,
                session_id,
                opcao.get('debt_id') or '',
                str(opcao.get('invoice_id') or ''),
                cpf_limpo,
                str(opcao.get('reference_month_raw') or ''),
                sess,
            ) or ''
        except Exception:
            logger.exception('[Qualidade] Falha ao obter PDF Nio fatura=%s', fatura_id)

    if pdf_url:
        fatura.pdf_url = pdf_url
        campos.append('pdf_url')

    if campos:
        campos.append('atualizado_em')
        fatura.save(update_fields=list(dict.fromkeys(campos)))

    if fatura.numero_fatura == 1:
        contrato.data_vencimento_fpd = fatura.data_vencimento
        contrato.valor_fatura_fpd = fatura.valor
        contrato.status_fatura_fpd = fatura.status
        contrato.save(update_fields=[
            'data_vencimento_fpd', 'valor_fatura_fpd', 'status_fatura_fpd', 'atualizado_em',
        ])
        # Aceite da 1ª fatura define o valor mensal de todas as demais
        if fatura.valor is not None and float(fatura.valor) > 0:
            contrato.faturas.exclude(pk=fatura.pk).update(
                valor=fatura.valor,
                atualizado_em=timezone.now(),
            )

    contrato.calcular_elegibilidade()

    return {
        'ok': True,
        'fatura_id': fatura.id,
        'pdf_url': fatura.pdf_url or '',
        'detalhe': detalhe_contrato_faturas(contrato_id),
    }


# ---------------------------------------------------------------------------
# Gestão de cobrança automática (preview + logs)
# ---------------------------------------------------------------------------

TIPO_COBRANCA_LABELS = {
    'd5_antes': 'Lembrete D−5',
    'd5_depois': 'Vencida D+5',
    'recorrente': 'Recorrente',
}


def limite_job_cobranca_nio() -> int:
    """0 = sem teto (envia todos os elegíveis). Valor > 0 limita a execução."""
    try:
        return max(0, int(getattr(settings, 'COBRANCA_NIO_LIMITE_JOB', 0) or 0))
    except (TypeError, ValueError):
        return 0


def pausa_envio_cobranca_segundos() -> float:
    try:
        ms = max(0, int(getattr(settings, 'COBRANCA_NIO_PAUSA_MS', 300) or 0))
    except (TypeError, ValueError):
        ms = 300
    return ms / 1000.0


def proximos_no_job_cobranca(faltam: int, limite_job: int) -> int:
    """Quantos o próximo job vai disparar. limite 0 = todos os faltantes."""
    n = max(0, int(faltam or 0))
    if limite_job and int(limite_job) > 0:
        return min(n, int(limite_job))
    return n


def _qs_faturas_abertas_cobranca() -> QuerySet:
    return (
        FaturaM10.objects.filter(status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO'])
        .exclude(status='PAGO')
        .select_related('contrato', 'contrato__venda')
        .order_by('id')
    )


def classificar_motivo_bloqueio_cobranca(ok_tratar: bool, motivo_dados: str) -> str:
    """Agrupa o motivo do KPI Bloqueados (órfão/CPF vs dados da fatura)."""
    if not ok_tratar:
        return 'Órfão / sem CPF'
    motivo = (motivo_dados or '').lower()
    if 'vencimento' in motivo:
        return 'Sem data de vencimento'
    if 'valor' in motivo:
        return 'Valor zerado ou vazio'
    return (motivo_dados or 'Dados incompletos')[:80]


def ja_enviou_template_cobranca_hoje(fatura: FaturaM10, *, dia: Optional[date] = None) -> bool:
    """Dedup do job automático: tentativa de template no dia local.

    Conta aceite da API e falha posterior da Meta (ex.: 131048). Sem isso o job
    reenviaria cobrança no mesmo dia e agravaria bloqueio de spam.
    """
    if HistoricoEnvioQualidade is None:
        return False
    alvo = dia or timezone.localdate()
    return HistoricoEnvioQualidade.objects.filter(
        fatura=fatura,
        canal='WHATSAPP',
        criado_em__date=alvo,
    ).filter(
        Q(sucesso=True)
        | Q(message_id__gt='')
        | Q(status_entrega='FALHOU')
    ).filter(
        Q(template_nome__gt='')
        | Q(mensagem__icontains='template')
        | Q(mensagem__startswith='[')
        | Q(origem='AUTO')
    ).exists()


def listar_alvos_cobranca_templates(
    *,
    hoje: Optional[date] = None,
    apenas: str = 'todos',
) -> list[tuple[str, FaturaM10]]:
    """
    Seleciona faturas-alvo do job (D−5, D+5, recorrente D+12/19…).
    Não aplica limite nem pode_tratar — a prévia/gestão filtram depois.
    """
    from datetime import timedelta

    dia = hoje or timezone.localdate()
    alvos: list[tuple[str, FaturaM10]] = []
    base = _qs_faturas_abertas_cobranca()

    if apenas in ('d5_antes', 'todos'):
        qs = base.filter(data_vencimento=dia + timedelta(days=5))
        for f in qs:
            alvos.append(('d5_antes', f))

    if apenas in ('d5_depois', 'todos'):
        qs = base.filter(data_vencimento=dia - timedelta(days=5))
        for f in qs:
            alvos.append(('d5_depois', f))

    if apenas in ('recorrente', 'todos'):
        for k in range(1, 8):
            dias = 5 + 7 * k
            qs = base.filter(data_vencimento=dia - timedelta(days=dias))
            for f in qs:
                alvos.append(('recorrente', f))

    return alvos


def preview_cobranca_templates_dia(
    *,
    data_ref: Optional[date] = None,
    limite_job: Optional[int] = None,
) -> dict[str, Any]:
    """
    Contadores objetivos para gestão do disparo automático das 09:00.

    Critérios (iguais ao management command):
    - fatura aberta com vencimento em D−5 / D+5 / D+12,19…
    - contrato tratável (não órfão / com CPF)
    - valor > 0 e vencimento preenchido
    - ainda sem WhatsApp template sucesso no dia
    """
    from crm_app.services.whatsapp.nio_templates import templates_habilitados

    dia = data_ref or timezone.localdate()
    if limite_job is None:
        limite_job = limite_job_cobranca_nio()
    else:
        try:
            limite_job = max(0, int(limite_job))
        except (TypeError, ValueError):
            limite_job = limite_job_cobranca_nio()
    por_tipo_bruto = {'d5_antes': 0, 'd5_depois': 0, 'recorrente': 0}
    por_tipo_elegivel = {'d5_antes': 0, 'd5_depois': 0, 'recorrente': 0}
    por_tipo_faltam = {'d5_antes': 0, 'd5_depois': 0, 'recorrente': 0}

    total_bruto = 0
    elegiveis = 0
    enviados = 0
    bloqueados = 0
    faltam = 0
    vistos: set[int] = set()
    exemplos_bloqueio: list[dict[str, Any]] = []
    por_motivo_bloqueio: dict[str, int] = {}
    faltam_fatura_ids: list[int] = []
    faltam_contratos: dict[int, Any] = {}

    for tipo, fatura in listar_alvos_cobranca_templates(hoje=dia):
        if fatura.id in vistos:
            continue
        vistos.add(fatura.id)
        total_bruto += 1
        por_tipo_bruto[tipo] = por_tipo_bruto.get(tipo, 0) + 1

        contrato = fatura.contrato
        ok_tratar = pode_tratar_contrato(contrato)
        ok_dados, motivo = validar_fatura_para_envio_cobranca(fatura)
        if not ok_tratar or not ok_dados:
            bloqueados += 1
            motivo_bloc = classificar_motivo_bloqueio_cobranca(ok_tratar, motivo)
            por_motivo_bloqueio[motivo_bloc] = por_motivo_bloqueio.get(motivo_bloc, 0) + 1
            if len(exemplos_bloqueio) < 8:
                exemplos_bloqueio.append({
                    'fatura_id': fatura.id,
                    'contrato_id': contrato.id,
                    'os': getattr(contrato, 'ordem_servico', '') or '',
                    'cliente': (contrato.cliente_nome or '')[:60],
                    'motivo': motivo_bloc,
                })
            continue

        elegiveis += 1
        por_tipo_elegivel[tipo] = por_tipo_elegivel.get(tipo, 0) + 1

        if ja_enviou_template_cobranca_hoje(fatura, dia=dia):
            enviados += 1
            continue

        faltam += 1
        por_tipo_faltam[tipo] = por_tipo_faltam.get(tipo, 0) + 1
        faltam_fatura_ids.append(fatura.id)
        faltam_contratos[fatura.id] = contrato

    faltam_sem_telefone = 0
    faltam_com_erro_hoje = 0
    faltam_nao_tentados = 0
    if faltam_fatura_ids and HistoricoEnvioQualidade is not None:
        erros_hoje = set(
            HistoricoEnvioQualidade.objects.filter(
                fatura_id__in=faltam_fatura_ids,
                canal='WHATSAPP',
                sucesso=False,
                criado_em__date=dia,
            ).values_list('fatura_id', flat=True)
        )
    else:
        erros_hoje = set()
    for fid in faltam_fatura_ids:
        contrato = faltam_contratos.get(fid)
        tel = ''
        if contrato is not None:
            tel = (enriquecer_contato_contrato(contrato).get('telefone') or '').strip()
        if not tel:
            faltam_sem_telefone += 1
        elif fid in erros_hoje:
            faltam_com_erro_hoje += 1
        else:
            faltam_nao_tentados += 1

    proximos_no_job = proximos_no_job_cobranca(faltam, limite_job)
    horario = HORARIO_JOB_COBRANCA
    if limite_job > 0:
        criterio_job = f'Job diário às {horario} (limite {limite_job}/execução)'
    else:
        criterio_job = (
            f'Job diário às {horario} (envia todos os elegíveis: D−5 · D+5 · recorrente)'
        )

    return {
        'data': dia.isoformat(),
        'horario_automatico': horario,
        'timezone': 'America/Sao_Paulo',
        'templates_habilitados': bool(templates_habilitados()),
        'limite_job': limite_job,
        'sem_limite': limite_job <= 0,
        'total_criterio': total_bruto,
        'elegiveis': elegiveis,
        'ja_enviados_hoje': enviados,
        'faltam': faltam,
        'faltam_detalhe': {
            'sem_telefone': faltam_sem_telefone,
            'com_erro_hoje': faltam_com_erro_hoje,
            'nao_tentados': faltam_nao_tentados,
        },
        'bloqueados': bloqueados,
        'por_motivo_bloqueio': por_motivo_bloqueio,
        'proximos_no_job': proximos_no_job,
        'por_tipo': {
            'criterio': por_tipo_bruto,
            'elegiveis': por_tipo_elegivel,
            'faltam': por_tipo_faltam,
        },
        'labels_tipo': TIPO_COBRANCA_LABELS,
        'criterios': [
            'Fatura NAO_PAGO / ATRASADO / AGUARDANDO',
            'Vencimento em D−5, D+5 ou D+12/19/26…',
            'Contrato tratável (não órfão, com CPF)',
            'Valor > 0 e vencimento preenchidos',
            'Sem WhatsApp template com sucesso no dia',
            criterio_job,
        ],
        'exemplos_bloqueio': exemplos_bloqueio,
    }


def status_busca_nio(log_id: int) -> dict[str, Any]:
    """Progresso de HistoricoBuscaFatura (Buscar Nio bulk)."""
    from crm_app.models import HistoricoBuscaFatura

    try:
        h = HistoricoBuscaFatura.objects.select_related('usuario').get(pk=log_id)
    except HistoricoBuscaFatura.DoesNotExist as exc:
        raise ValueError(f'Busca Nio #{log_id} não encontrada.') from exc

    logs = h.logs if isinstance(h.logs, dict) else {}
    progresso = logs.get('progresso') if isinstance(logs.get('progresso'), dict) else {}
    contratos_feitos = int(progresso.get('contratos_feitos') or 0)
    contratos_total = int(progresso.get('contratos_total') or h.total_contratos or 0)
    ultimo = progresso.get('ultimo_contrato') or ''
    detalhes = logs.get('detalhes') if isinstance(logs.get('detalhes'), list) else []
    recentes = detalhes[-12:] if detalhes else []

    pct = 0.0
    if h.status in ('CONCLUIDA', 'ERRO', 'CANCELADA'):
        pct = 100.0
    elif contratos_total > 0:
        pct = min(99.0, round(100.0 * contratos_feitos / contratos_total, 1))

    duracao = None
    if h.inicio_em:
        fim = h.termino_em or timezone.now()
        duracao = round((fim - h.inicio_em).total_seconds(), 1)

    return {
        'id': h.id,
        'status': h.status,
        'tipo_busca': h.tipo_busca,
        'safra': h.safra or '',
        'mensagem': h.mensagem or '',
        'inicio_em': _iso_dt_local(h.inicio_em),
        'termino_em': _iso_dt_local(h.termino_em),
        'duracao_segundos': float(h.duracao_segundos) if h.duracao_segundos is not None else duracao,
        'total_contratos': h.total_contratos or contratos_total,
        'contratos_feitos': contratos_feitos,
        'total_faturas': h.total_faturas or 0,
        'faturas_sucesso': h.faturas_sucesso or 0,
        'faturas_erro': h.faturas_erro or 0,
        'faturas_nao_disponiveis': h.faturas_nao_disponiveis or 0,
        'ultimo_contrato': ultimo,
        'percentual': pct,
        'em_andamento': h.status == 'EM_ANDAMENTO',
        'recentes': recentes,
    }


def listar_gestao_envios_qualidade(
    *,
    data_ref: Optional[date] = None,
    origem: str = '',
    sucesso: Optional[bool] = None,
    canal: str = 'WHATSAPP',
    q: str = '',
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Painel de logs/gestão de envios (dia + filtros)."""
    if HistoricoEnvioQualidade is None:
        return {
            'resumo': {},
            'itens': [],
            'page': 1,
            'page_size': page_size,
            'total': 0,
            'preview': preview_cobranca_templates_dia(data_ref=data_ref),
        }

    dia = data_ref or timezone.localdate()
    qs = (
        HistoricoEnvioQualidade.objects.filter(criado_em__date=dia)
        .select_related('contrato', 'fatura', 'enviado_por')
        .order_by('-criado_em')
    )
    if canal:
        qs = qs.filter(canal=canal.upper())
    if origem:
        qs = qs.filter(origem=origem.upper())
    if sucesso is not None:
        qs = qs.filter(sucesso=sucesso)
    q = (q or '').strip()
    if q:
        q_digits = re.sub(r'\D', '', q)
        filtros_gestao = (
            Q(contrato__ordem_servico__icontains=q)
            | Q(contrato__cliente_nome__icontains=q)
            | Q(contrato__numero_contrato__icontains=q)
            | Q(destinatario__icontains=q)
            | Q(template_nome__icontains=q)
        )
        if q_digits and len(q_digits) >= 8:
            qs = qs.annotate(
                _gestao_tel1=_StripNonDigits(
                    Coalesce(F('contrato__venda__telefone1'), Value(''))
                ),
                _gestao_tel2=_StripNonDigits(
                    Coalesce(F('contrato__venda__telefone2'), Value(''))
                ),
            )
            for variante in _variantes_busca_telefone(q_digits):
                filtros_gestao |= (
                    Q(_gestao_tel1__contains=variante)
                    | Q(_gestao_tel2__contains=variante)
                    | Q(destinatario__icontains=variante)
                )
        qs = qs.filter(filtros_gestao)

    # Resumo do dia (WhatsApp) independente dos filtros de listagem, exceto data
    base_dia = HistoricoEnvioQualidade.objects.filter(
        criado_em__date=dia,
        canal='WHATSAPP',
    )
    resumo = {
        'data': dia.isoformat(),
        'whatsapp_total': base_dia.count(),
        'whatsapp_sucesso': base_dia.filter(sucesso=True).count(),
        'whatsapp_erro': base_dia.filter(sucesso=False).count(),
        'whatsapp_falhou_entrega': base_dia.filter(status_entrega='FALHOU').count(),
        'auto_sucesso': base_dia.filter(origem='AUTO', sucesso=True).count(),
        'manual_sucesso': base_dia.filter(origem='MANUAL', sucesso=True).count(),
        # Legado sem origem/template: conta como auto se sem usuário
        'sem_usuario_sucesso': base_dia.filter(
            enviado_por__isnull=True, sucesso=True
        ).count(),
    }

    total = qs.count()
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 50)))
    offset = (page - 1) * page_size
    itens: list[dict[str, Any]] = []
    for h in qs[offset : offset + page_size]:
        origem_exibida = h.origem or (
            'AUTO' if not h.enviado_por_id else 'MANUAL'
        )
        itens.append({
            'id': h.id,
            'criado_em': _iso_dt_local(h.criado_em),
            'canal': h.canal,
            'origem': origem_exibida,
            'template_nome': h.template_nome or '',
            'sucesso': bool(h.sucesso),
            'erro': (h.erro or '')[:300],
            'message_id': h.message_id or '',
            'status_entrega': h.status_entrega or '',
            'erro_codigo': h.erro_codigo or '',
            'destinatario': h.destinatario or '',
            'mensagem': (h.mensagem or '')[:180],
            'contrato_id': h.contrato_id,
            'os': getattr(h.contrato, 'ordem_servico', '') or '',
            'cliente': (h.contrato.cliente_nome or '')[:80],
            'cpf_cliente': (getattr(h.contrato, 'cpf_cliente', None) or '').strip(),
            'fatura_id': h.fatura_id,
            'valor': float(h.fatura.valor) if h.fatura_id and h.fatura and h.fatura.valor is not None else None,
            'vencimento': (
                h.fatura.data_vencimento.isoformat()
                if h.fatura_id and h.fatura and h.fatura.data_vencimento
                else None
            ),
            'enviado_por': (
                (h.enviado_por.get_full_name() or h.enviado_por.username)
                if h.enviado_por_id
                else None
            ),
        })

    return {
        'resumo': resumo,
        'itens': itens,
        'page': page,
        'page_size': page_size,
        'total': total,
        'preview': preview_cobranca_templates_dia(data_ref=dia),
    }


def _normalizar_fila_envio_atrasados(fila: str) -> str:
    """Fila do botão de reenvio: um bucket ou todos os atrasados do mês."""
    f = (fila or '').strip().lower()
    if f in (FILA_ATRASADOS_LT60, 'atrasados_-60', 'atrasados_menos_60'):
        return FILA_ATRASADOS_LT60
    if f in (FILA_ATRASADOS_GTE60, 'atrasados_+60', 'atrasados_mais_60'):
        return FILA_ATRASADOS_GTE60
    return FILA_ATRASADOS


def _queryset_universo_tratamento(
    lente: str,
    mes: str,
) -> QuerySet[ContratoM10]:
    """Mesmo universo da aba Tratamento (planilha FPD MATCHED / safra instalação)."""
    lente_norm = (lente or LENTE_VENCIMENTO).strip().lower()
    data_inicio, data_fim = mes_range(mes)
    if lente_norm == LENTE_INSTALACAO:
        queryset = ContratoM10.objects.filter(
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
        )
    else:
        contrato_ids = (
            ImportacaoFPD.objects.filter(
                indicador='FPD',
                dt_venc_orig__gte=data_inicio,
                dt_venc_orig__lt=data_fim,
                match_status='MATCHED',
                contrato_m10_id__isnull=False,
            )
            .values_list('contrato_m10_id', flat=True)
            .distinct()
        )
        queryset = ContratoM10.objects.filter(id__in=contrato_ids)
    if _contrato_tem_campo('orfao'):
        queryset = queryset.filter(orfao=False)
    return queryset


def _fatura1_aberta(contrato: ContratoM10) -> Optional[FaturaM10]:
    fatura = next(
        (f for f in contrato.faturas.all() if f.numero_fatura == 1),
        None,
    )
    if fatura is None:
        fatura = FaturaM10.objects.filter(contrato=contrato, numero_fatura=1).first()
    if fatura is None or _fatura_esta_fechada(fatura.status):
        return None
    return fatura


def preview_envio_atrasados(
    *,
    lente: str,
    mes: str,
    fila: str = FILA_ATRASADOS,
) -> dict[str, Any]:
    """Conta atrasados do mês que o botão da aba Tratamento vai disparar."""
    fila_eff = _normalizar_fila_envio_atrasados(fila)
    qs = _aplicar_filtro_fila(
        _queryset_universo_tratamento(lente, mes),
        fila_eff,
    ).select_related('venda').prefetch_related('faturas')
    total = 0
    a_enviar = 0
    ja_hoje = 0
    bloqueados = 0
    for contrato in qs:
        fatura = _fatura1_aberta(contrato)
        if fatura is None:
            continue
        total += 1
        if not pode_tratar_contrato(contrato):
            bloqueados += 1
            continue
        ok_dados, _motivo = validar_fatura_para_envio_cobranca(fatura)
        if not ok_dados:
            bloqueados += 1
            continue
        if ja_enviou_template_cobranca_hoje(fatura):
            ja_hoje += 1
            continue
        a_enviar += 1
    return {
        'mes': mes,
        'lente': (lente or LENTE_VENCIMENTO).strip().lower(),
        'fila': fila_eff,
        'total': total,
        'a_enviar': a_enviar,
        'ja_enviados_hoje': ja_hoje,
        'bloqueados': bloqueados,
    }


def enviar_cobranca_atrasados_lote(
    *,
    lente: str,
    mes: str,
    user: Any,
    fila: str = FILA_ATRASADOS,
    forcar: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Envia nio_fatura_reducao_sinal_v1 aos atrasados do mês (aba Tratamento).

    Pula quem já teve WhatsApp com sucesso no dia, salvo ``forcar``.
    Não usa o recorte D−5/D+5/recorrente do job das 09:00 — cobre a fila
    operacional de FPD.
    """
    fila_eff = _normalizar_fila_envio_atrasados(fila)
    qs = _aplicar_filtro_fila(
        _queryset_universo_tratamento(lente, mes),
        fila_eff,
    ).select_related('venda').prefetch_related('faturas').order_by('id')

    enviados = 0
    erros = 0
    pulados = 0
    pausa = 0.0 if dry_run else pausa_envio_cobranca_segundos()
    detalhes: list[dict[str, Any]] = []

    for contrato in qs:
        fatura = _fatura1_aberta(contrato)
        if fatura is None:
            pulados += 1
            continue
        if not pode_tratar_contrato(contrato):
            pulados += 1
            continue
        ok_dados, motivo = validar_fatura_para_envio_cobranca(fatura)
        if not ok_dados:
            pulados += 1
            if len(detalhes) < 20:
                detalhes.append({
                    'contrato_id': contrato.id,
                    'os': contrato.ordem_servico or '',
                    'status': 'pulado',
                    'motivo': motivo,
                })
            continue
        if not forcar and ja_enviou_template_cobranca_hoje(fatura):
            pulados += 1
            continue
        if dry_run:
            enviados += 1
            continue
        result = enviar_cobranca_whatsapp(
            contrato.id,
            fatura.id,
            user,
            modo='reducao_sinal',
        )
        if result.get('ok'):
            enviados += 1
        else:
            erros += 1
            if len(detalhes) < 20:
                detalhes.append({
                    'contrato_id': contrato.id,
                    'os': contrato.ordem_servico or '',
                    'status': 'erro',
                    'motivo': result.get('erro') or 'Falha no envio',
                })
        if pausa > 0:
            time.sleep(pausa)

    logger.info(
        '[Qualidade] Reenvio atrasados mes=%s fila=%s enviados=%s erros=%s pulados=%s dry=%s',
        mes, fila_eff, enviados, erros, pulados, dry_run,
    )
    return {
        'ok': erros == 0,
        'mes': mes,
        'lente': (lente or LENTE_VENCIMENTO).strip().lower(),
        'fila': fila_eff,
        'enviados': enviados,
        'erros': erros,
        'pulados': pulados,
        'dry_run': dry_run,
        'detalhes': detalhes,
    }


def iniciar_envio_atrasados_async(
    *,
    lente: str,
    mes: str,
    user: Any,
    fila: str = FILA_ATRASADOS,
    forcar: bool = False,
) -> dict[str, Any]:
    """Dispara o lote em thread para não estourar timeout HTTP."""
    preview = preview_envio_atrasados(lente=lente, mes=mes, fila=fila)
    if int(preview.get('a_enviar') or 0) <= 0:
        return {
            'ok': True,
            'iniciado': False,
            'mensagem': 'Nenhum atrasado pendente de WhatsApp hoje neste recorte.',
            **preview,
        }
    user_id = getattr(user, 'pk', None)

    def _run() -> None:
        import django.db

        django.db.close_old_connections()
        try:
            usuario = None
            if user_id:
                from django.contrib.auth import get_user_model

                usuario = get_user_model().objects.filter(pk=user_id).first()
            enviar_cobranca_atrasados_lote(
                lente=lente,
                mes=mes,
                user=usuario,
                fila=fila,
                forcar=forcar,
            )
        except Exception:
            logger.exception(
                '[Qualidade] Falha no reenvio async mes=%s fila=%s', mes, fila
            )
        finally:
            django.db.close_old_connections()

    thread = threading.Thread(
        target=_run,
        daemon=True,
        name='qualidade-envio-atrasados',
    )
    thread.start()
    return {
        'ok': True,
        'iniciado': True,
        'mensagem': (
            f"Envio iniciado para {preview.get('a_enviar') or 0} atrasado(s). "
            'Acompanhe o resultado na aba Envios.'
        ),
        **preview,
    }
