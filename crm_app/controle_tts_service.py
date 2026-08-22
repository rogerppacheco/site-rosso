"""
Controle de TT's: fila por dias sem vender (OSAB) e marcações diárias.
Usado pela API interna, VENDER (fila OSAB) e CRÉDITO (menor carga do dia).
"""
import logging
import random
from datetime import timedelta
from typing import List, Optional, Set

from django.conf import settings
from django.db.models import F, Max, Q
from django.utils import timezone

from crm_app.models import (
    ControleTTCreditoCursorPap,
    ControleTTCreditoUsoDiario,
    ControleTTDiaTratado,
    ImportacaoOsab,
)

logger = logging.getLogger(__name__)

SITUACOES_VENDA_VALIDA_OSAB = [
    "Concluído",
    "Pendência Cliente",
    "Cancelado",
    "Pendência Técnica",
    "Em Aprovisionamento",
]


def controle_tts_listar_ordenado():
    """
    Lista de TTs com última venda válida e dias sem vender; ordenado por dias sem vender (decrescente).
    Mesma lógica do endpoint GET controle-tts/.
    """
    hoje = timezone.localdate()
    ontem = hoje - timedelta(days=1)
    dois_meses_atras = hoje - timedelta(days=60)
    matriculas_qs = (
        ImportacaoOsab.objects.filter(data_abertura__gte=dois_meses_atras, matricula_vendedor__isnull=False)
        .exclude(matricula_vendedor="")
        .values_list("matricula_vendedor", flat=True)
        .distinct()
    )
    matriculas = list(matriculas_qs)
    filtro_situacao_valida = Q(situacao__in=SITUACOES_VENDA_VALIDA_OSAB)
    resultado = []
    for mat in matriculas:
        ultima = (
            ImportacaoOsab.objects.filter(matricula_vendedor=mat)
            .filter(filtro_situacao_valida)
            .filter(data_abertura__isnull=False)
            .aggregate(Max("data_abertura"))
        )
        ultima_venda = ultima.get("data_abertura__max")
        if ultima_venda is not None:
            if hasattr(ultima_venda, "date"):
                ultima_venda = ultima_venda.date()
            dias_sem_vender = (ontem - ultima_venda).days
        else:
            dias_sem_vender = None
        resultado.append(
            {
                "matricula_vendedor": mat,
                "ultima_venda": ultima_venda.isoformat() if ultima_venda else None,
                "dias_sem_vender": dias_sem_vender,
            }
        )

    def sort_key(item):
        d = item["dias_sem_vender"]
        if d is None:
            return -1
        return -d

    resultado.sort(key=sort_key)
    return resultado


def obter_matricula_tt_para_novo_pedido_pap(matricula_fallback: str) -> str:
    """
    Próximo TT da fila (não marcado hoje), para preencher o vendedor no PAP — fluxo VENDER.
    Ordenação: maior dias sem vender (OSAB) primeiro.
    Se não houver próximo, usa matricula_fallback (cadastro do operador).
    """
    matricula_fallback = (matricula_fallback or "").strip()
    lista = controle_tts_listar_ordenado()
    hoje = timezone.localdate()
    marcadas = set(
        ControleTTDiaTratado.objects.filter(data=hoje).values_list("matricula_vendedor", flat=True)
    )
    lista_filtrada = [x for x in lista if x["matricula_vendedor"] not in marcadas]
    proximo = lista_filtrada[0] if lista_filtrada else None
    if proximo and proximo.get("matricula_vendedor"):
        m = str(proximo["matricula_vendedor"]).strip()
        if m:
            logger.info("[Controle TT] PAP novo pedido: TT da vez = %s", m)
            return m
    logger.info(
        "[Controle TT] PAP novo pedido: sem próximo na fila — usando operador %s",
        matricula_fallback or "(vazio)",
    )
    return matricula_fallback


def _max_consultas_credito_por_tt_dia() -> int:
    return max(1, int(getattr(settings, "PAP_CREDITO_MAX_CONSULTAS_POR_TT_DIA", 6)))


def _mapa_uso_credito_hoje(matriculas: list[str]) -> dict[str, int]:
    hoje = timezone.localdate()
    if not matriculas:
        return {}
    try:
        rows = ControleTTCreditoUsoDiario.objects.filter(
            data=hoje,
            matricula_vendedor__in=matriculas,
        )
        return {r.matricula_vendedor: r.consultas for r in rows}
    except Exception as e:
        logger.warning(
            "[Controle TT] Tabela de uso diário indisponível (%s) — assumindo uso zero",
            e,
        )
        return {}


def _normalizar_matriculas_ordenadas(candidatos: List[str]) -> list[str]:
    """Remove vazios/duplicados preservando a ordem do dropdown do PAP."""
    vistas: set[str] = set()
    ordenadas: list[str] = []
    for raw in candidatos:
        mat = str(raw or "").strip()
        chave = mat.upper()
        if not mat or chave in vistas:
            continue
        vistas.add(chave)
        ordenadas.append(mat)
    return ordenadas


def obter_proximo_tt_lista_pap(
    candidatos: List[str],
    *,
    bo_matricula: str,
    excluir: Optional[Set[str]] = None,
    matricula_fallback: str = "",
) -> str:
    """
    Percorre a lista do PAP em sequência (1º, 2º, 3º…).

    O cursor fica em ControleTTCreditoCursorPap por login BO/PDV: a próxima
    consulta começa depois da última matrícula entregue e volta ao início ao
    chegar no fim da lista. Matrículas em `excluir` (falharam nesta sessão)
    são puladas sem avançar o cursor de forma permanente além da escolha.
    """
    lista = _normalizar_matriculas_ordenadas(candidatos)
    fallback = (matricula_fallback or "").strip()
    if not lista:
        logger.warning(
            "[Controle TT] Crédito (PAP sequencial): lista vazia — fallback %s",
            fallback or "(vazio)",
        )
        return fallback

    excluir_norm = {
        (m or "").strip().upper() for m in (excluir or set()) if (m or "").strip()
    }
    chave_bo = (bo_matricula or "").strip() or "sem-bo"
    cursor, _ = ControleTTCreditoCursorPap.objects.get_or_create(
        bo_matricula=chave_bo,
        defaults={"ultima_matricula": "", "posicao": 0},
    )

    inicio = 0
    ultima = (cursor.ultima_matricula or "").strip().upper()
    if ultima:
        for idx, mat in enumerate(lista):
            if mat.upper() == ultima:
                inicio = (idx + 1) % len(lista)
                break

    for offset in range(len(lista)):
        idx = (inicio + offset) % len(lista)
        escolhido = lista[idx]
        if escolhido.upper() in excluir_norm:
            continue
        ControleTTCreditoCursorPap.objects.filter(pk=cursor.pk).update(
            ultima_matricula=escolhido,
            posicao=idx,
        )
        logger.info(
            "[Controle TT] Crédito (PAP sequencial): TT=%s pos=%s/%s bo=%s",
            escolhido,
            idx + 1,
            len(lista),
            chave_bo,
        )
        return escolhido

    logger.warning(
        "[Controle TT] Crédito (PAP sequencial): todos excluídos (n=%s) — fallback %s",
        len(excluir_norm),
        fallback or "(vazio)",
    )
    return fallback


def obter_matricula_tt_para_credito_pap(
    matricula_fallback: str,
    excluir: Optional[Set[str]] = None,
    candidatos: Optional[List[str]] = None,
    *,
    bo_matricula: str = "",
    sequencial_pap: bool = False,
) -> str:
    """
    Escolhe TT para consulta de crédito.

    Com candidatos do dropdown do PAP e sequencial_pap=True: percorre a lista
    na ordem (1º, 2º, 3º…) usando cursor por BO — evita matrículas da OSAB
    que não existem no PDV.

    Sem lista do PAP (legado OSAB): prioriza quem tem MENOS consultas hoje,
    respeita teto PAP_CREDITO_MAX_CONSULTAS_POR_TT_DIA e sorteia em empate.
    """
    matricula_fallback = (matricula_fallback or "").strip()
    excluir_norm = {(m or "").strip().upper() for m in (excluir or set()) if (m or "").strip()}

    if candidatos is not None:
        matriculas = _normalizar_matriculas_ordenadas(list(candidatos))
        origem = "PAP"
        if sequencial_pap and matriculas:
            return obter_proximo_tt_lista_pap(
                matriculas,
                bo_matricula=bo_matricula,
                excluir=excluir_norm,
                matricula_fallback=matricula_fallback,
            )
    else:
        lista = controle_tts_listar_ordenado()
        matriculas = [
            str(x["matricula_vendedor"]).strip()
            for x in lista
            if x.get("matricula_vendedor")
        ]
        origem = "OSAB"
    if not matriculas:
        logger.warning(
            "[Controle TT] Crédito: fila %s vazia — fallback %s",
            origem,
            matricula_fallback or "(vazio)",
        )
        return matricula_fallback

    uso_map = _mapa_uso_credito_hoje(matriculas)
    max_dia = _max_consultas_credito_por_tt_dia()

    def uso(mat: str) -> int:
        return uso_map.get(mat, 0)

    def disponivel(mat: str) -> bool:
        return mat.strip().upper() not in excluir_norm

    candidatos_livres = [m for m in matriculas if disponivel(m) and uso(m) < max_dia]
    if not candidatos_livres:
        candidatos_livres = [m for m in matriculas if disponivel(m)]
    if not candidatos_livres:
        logger.warning(
            "[Controle TT] Crédito: nenhum TT disponível (excluídos=%s) — fallback %s",
            len(excluir_norm),
            matricula_fallback or "(vazio)",
        )
        return matricula_fallback

    min_uso = min(uso(m) for m in candidatos_livres)
    empate = [m for m in candidatos_livres if uso(m) == min_uso]
    escolhido = random.choice(empate)
    logger.info(
        "[Controle TT] Crédito (%s): TT=%s uso_hoje=%s min=%s empate=%s teto=%s",
        origem,
        escolhido,
        uso(escolhido),
        min_uso,
        len(empate),
        max_dia,
    )
    return escolhido


def registrar_uso_tt_credito(matricula_vendedor: str) -> None:
    """Incrementa contador de consultas de crédito do TT no dia."""
    m = (matricula_vendedor or "").strip()
    if not m:
        return
    hoje = timezone.localdate()
    try:
        obj, _ = ControleTTCreditoUsoDiario.objects.get_or_create(
            matricula_vendedor=m,
            data=hoje,
            defaults={"consultas": 0},
        )
        ControleTTCreditoUsoDiario.objects.filter(pk=obj.pk).update(
            consultas=F("consultas") + 1
        )
        logger.info("[Controle TT] Crédito: uso registrado para %s em %s", m, hoje.isoformat())
    except Exception as e:
        logger.warning("[Controle TT] Falha ao registrar uso crédito %s: %s", m, e)


def pular_tt_credito_indisponivel(matricula_vendedor: str) -> None:
    """
    Marca TT no teto do dia (ex.: inexistente no PAP) para não reescolher na mesma sessão.
    """
    m = (matricula_vendedor or "").strip()
    if not m:
        return
    hoje = timezone.localdate()
    max_dia = _max_consultas_credito_por_tt_dia()
    try:
        ControleTTCreditoUsoDiario.objects.update_or_create(
            matricula_vendedor=m,
            data=hoje,
            defaults={"consultas": max_dia},
        )
        logger.info("[Controle TT] Crédito: TT %s marcado indisponível (teto %s)", m, max_dia)
    except Exception as e:
        logger.warning("[Controle TT] Falha ao pular TT crédito %s: %s", m, e)


def marcar_tt_tratado_apos_geracao_os(matricula_vendedor: str) -> None:
    """
    Marca tratado no dia atual para a matrícula usada no PAP (O.S. gerada).
    Idempotente (update_or_create). usuario=None (automático).
    """
    m = (matricula_vendedor or "").strip()
    if not m:
        return
    hoje = timezone.localdate()
    try:
        ControleTTDiaTratado.objects.update_or_create(
            matricula_vendedor=m,
            data=hoje,
            defaults={"tipo": ControleTTDiaTratado.TIPO_TRATADO, "usuario": None},
        )
        logger.info("[Controle TT] Marcado tratado (O.S.) para %s em %s", m, hoje.isoformat())
    except Exception as e:
        logger.warning("[Controle TT] Falha ao marcar tratado para %s: %s", m, e)
