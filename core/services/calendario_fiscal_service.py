"""
Serviço do calendário fiscal: estrutura do mês, atualização em lote de pesos/observações
e totais/navegação.

Centraliza a regra de negócio de dias fiscais (peso venda, peso instalação por dia),
incluindo a criação sob demanda de dias ainda não cadastrados com valores padrão
(domingo=0, sábado=0.5/0, demais=1.0) e o ajuste da sequence do PostgreSQL quando
houver concorrência na criação.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Any, Literal

TipoPesoFiscal = Literal['VB', 'GR']

from django.db import IntegrityError, connection
from django.db.models import Sum

from core.models import DiaFiscal

logger = logging.getLogger(__name__)


def _corrigir_sequence_diafiscal() -> None:
    """
    Sincroniza a sequence do id de core_diafiscal com o MAX(id).
    Necessário quando get_or_create falha por race condition e o próximo id
    já foi consumido por outra transação.
    """
    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('core_diafiscal', 'id'),
                    COALESCE((SELECT MAX(id) FROM core_diafiscal), 0) + 1
                )
                """
            )
    except Exception as e:
        logger.warning("Não foi possível corrigir sequence core_diafiscal: %s", e)


def fracao_dia_corrente(agora_local: datetime) -> float:
    """Fração do dia civil já decorrida (mín. 1h), alinhada à projeção do dashboard."""
    meia_noite = agora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    decorrido_s = (agora_local - meia_noite).total_seconds()
    return min(max(decorrido_s / 86400.0, 1.0 / 24.0), 1.0)


def carregar_mapa_fiscal(inicio: date, fim: date) -> dict[date, DiaFiscal]:
    """Mapa data → DiaFiscal para consultas em lote no painel de performance."""
    return {
        d.data: d
        for d in DiaFiscal.objects.filter(data__range=(inicio, fim))
    }


def peso_unitario_dia(
    data_atual: date,
    tipo: TipoPesoFiscal,
    mapa: dict[date, DiaFiscal] | None = None,
) -> float:
    """Retorna peso_venda (VB) ou peso_instalacao (GR) do dia, com fallback padrão."""
    if mapa and data_atual in mapa:
        p_venda = float(mapa[data_atual].peso_venda)
        p_inst = float(mapa[data_atual].peso_instalacao)
    else:
        p_venda, p_inst = _pesos_padrao_por_weekday(data_atual)
    return p_venda if tipo == 'VB' else p_inst


def somar_pesos_periodo(
    inicio: date,
    fim: date,
    *,
    limite: date,
    tipo: TipoPesoFiscal = 'VB',
    mapa: dict[date, DiaFiscal] | None = None,
    hoje_ref: date | None = None,
    agora_local: datetime | None = None,
    fracionar_hoje: bool = False,
) -> float:
    """
    Soma pesos fiscais de inicio até min(fim, limite).
    Quando fracionar_hoje=True, aplica fração horária apenas no hoje_ref.
    """
    total = 0.0
    limite_efetivo = min(fim, limite)
    if inicio > limite_efetivo:
        return 0.0
    data_iter = inicio
    while data_iter <= limite_efetivo:
        peso = peso_unitario_dia(data_iter, tipo, mapa)
        if fracionar_hoje and hoje_ref and agora_local and data_iter == hoje_ref:
            peso *= fracao_dia_corrente(agora_local)
        total += peso
        data_iter += timedelta(days=1)
    return total


def _pesos_padrao_por_weekday(data_atual: date) -> tuple[float, float]:
    """
    Retorna (peso_venda, peso_instalacao) padrão para a data conforme dia da semana.
    Domingo (6) = 0/0; sábado (5) = 0.5/0; demais = 1.0/1.0.
    """
    weekday = data_atual.weekday()
    p_venda = 0.0 if weekday == 6 else (0.5 if weekday == 5 else 1.0)
    p_inst = 0.0 if weekday >= 5 else 1.0
    return p_venda, p_inst


def obter_estrutura_calendario(ano: int, mes: int) -> list[list[DiaFiscal | None]]:
    """
    Monta a grade do calendário do mês com um DiaFiscal por dia útil/célula.

    Para cada dia do mês garante que exista um registro em DiaFiscal (criando com
    pesos padrão por dia da semana quando não existir). Em caso de IntegrityError
    (concorrência), corrige a sequence e tenta obter/criar de novo para não falhar
    a tela para o usuário.
    """
    cal = calendar.Calendar(firstweekday=6).monthdayscalendar(ano, mes)
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])

    dias_banco: dict[date, DiaFiscal] = {
        d.data: d
        for d in DiaFiscal.objects.filter(
            data__range=(primeiro_dia_mes, ultimo_dia_mes)
        )
    }

    estrutura: list[list[DiaFiscal | None]] = []

    for semana in cal:
        semana_processada: list[DiaFiscal | None] = []
        for dia_numero in semana:
            if dia_numero == 0:
                semana_processada.append(None)
                continue

            data_atual = date(ano, mes, dia_numero)
            if data_atual not in dias_banco:
                p_venda, p_inst = _pesos_padrao_por_weekday(data_atual)
                try:
                    dia_obj, _ = DiaFiscal.objects.get_or_create(
                        data=data_atual,
                        defaults={"peso_venda": p_venda, "peso_instalacao": p_inst},
                    )
                except IntegrityError:
                    _corrigir_sequence_diafiscal()
                    dia_obj = DiaFiscal.objects.filter(data=data_atual).first()
                    if not dia_obj:
                        dia_obj, _ = DiaFiscal.objects.get_or_create(
                            data=data_atual,
                            defaults={
                                "peso_venda": p_venda,
                                "peso_instalacao": p_inst,
                            },
                        )
                dias_banco[data_atual] = dia_obj

            semana_processada.append(dias_banco[data_atual])
        estrutura.append(semana_processada)

    return estrutura


def atualizar_dias_fiscais_lote(
    dias_ids: list[str],
    pesos_venda: list[str],
    pesos_inst: list[str],
    obs_list: list[str],
) -> None:
    """
    Atualiza em lote os dias fiscais com os pesos e observações vindos do POST.

    Aceita listas de mesmo tamanho; índices inválidos (ValueError ao converter
    número ou DiaFiscal.DoesNotExist) são ignorados para que um dado ruim não
    impeça a persistência dos demais.
    """
    for i, d_id in enumerate(dias_ids):
        try:
            dia = DiaFiscal.objects.get(id=int(d_id))
            p_venda_str = (pesos_venda[i] or "").replace(",", ".")
            p_inst_str = (pesos_inst[i] or "").replace(",", ".")
            dia.peso_venda = float(p_venda_str) if p_venda_str else 0.0
            dia.peso_instalacao = float(p_inst_str) if p_inst_str else 0.0
            dia.observacao = (obs_list[i] or "").strip() or None
            dia.save()
        except (ValueError, DiaFiscal.DoesNotExist, IndexError) as e:
            logger.debug("Dia fiscal lote: ignorando índice %s (%s).", i, e)
            continue


def obter_totais_e_navegacao(ano: int, mes: int) -> dict[str, Any]:
    """
    Retorna os totais do mês (soma dos pesos venda e instalação) e as datas
    de navegação para o mês anterior e próximo, além do nome do mês.
    """
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])

    totais = DiaFiscal.objects.filter(
        data__range=(primeiro_dia_mes, ultimo_dia_mes)
    ).aggregate(
        total_vb=Sum("peso_venda"),
        total_gross=Sum("peso_instalacao"),
    )

    nav_ant = date(ano, mes, 1) - timedelta(days=1)
    nav_prox = (date(ano, mes, 1) + timedelta(days=32)).replace(day=1)

    return {
        "totais": totais,
        "nome_mes": calendar.month_name[mes],
        "nav_ant": nav_ant,
        "nav_prox": nav_prox,
    }


def obter_contexto_calendario(
    ano: int,
    mes: int,
    modo_iframe: bool = False,
) -> dict[str, Any]:
    """
    Monta o contexto completo para o template do calendário fiscal:
    grade do mês, totais, navegação e flag de exibição em iframe.
    """
    estrutura = obter_estrutura_calendario(ano, mes)
    nav = obter_totais_e_navegacao(ano, mes)

    return {
        "calendario": estrutura,
        "mes": mes,
        "ano": ano,
        "totais": nav["totais"],
        "nome_mes": nav["nome_mes"],
        "nav_ant": nav["nav_ant"],
        "nav_prox": nav["nav_prox"],
        "modo_iframe": modo_iframe,
    }
