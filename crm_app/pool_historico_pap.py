# crm_app/pool_historico_pap.py
"""Pool de logins Diretoria para busca do histórico PAP no Funil."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import Q

logger = logging.getLogger(__name__)

MSG_NENHUM_LOGIN = (
    "Nenhum usuário Diretoria está liberado para buscar o histórico PAP. "
    "Marque “Autorizar busca do histórico PAP” na Governança e cadastre matrícula/senha PAP."
)

MSG_TODOS_EM_USO = (
    "Todos os logins Diretoria autorizados para o histórico PAP estão em uso no momento. "
    "Aguarde a busca atual terminar ou libere outro Diretoria com a mesma permissão."
)


def _tem_credencial(usuario) -> bool:
    return bool((getattr(usuario, "matricula_pap", None) or "").strip()) and bool(
        (getattr(usuario, "senha_pap", None) or "").strip()
    )


def candidatos_historico_pap():
    """Usuários Diretoria ativos com flag + matrícula/senha PAP."""
    from usuarios.models import Usuario

    return (
        Usuario.objects.filter(is_active=True, autorizar_historico_pap=True)
        .filter(
            Q(perfil__nome__iexact="Diretoria")
            | Q(perfil__cod_perfil__iexact="diretoria")
            | Q(groups__name__iexact="Diretoria")
        )
        .exclude(Q(matricula_pap__isnull=True) | Q(matricula_pap__exact=""))
        .exclude(Q(senha_pap__isnull=True) | Q(senha_pap__exact=""))
        .select_related("perfil")
        .distinct()
        .order_by("username")
    )


def ids_em_uso() -> set[int]:
    """Logins ocupados por busca de histórico ou pelo pool BO do WhatsApp."""
    from crm_app.models import HistoricoPapBusca, PapBoEmUso

    hist = set(
        HistoricoPapBusca.objects.filter(
            status__in=[
                HistoricoPapBusca.STATUS_PENDENTE,
                HistoricoPapBusca.STATUS_EM_ANDAMENTO,
            ],
            login_pap_id__isnull=False,
        ).values_list("login_pap_id", flat=True)
    )
    bo = set(PapBoEmUso.objects.values_list("bo_usuario_id", flat=True))
    return hist | bo


def resumo_pool() -> dict:
    cand = list(candidatos_historico_pap())
    ocupados = ids_em_uso()
    livres = [u for u in cand if u.id not in ocupados and _tem_credencial(u)]
    return {
        "total_autorizados": len(cand),
        "disponiveis": len(livres),
        "em_uso": len([u for u in cand if u.id in ocupados]),
        "logins_disponiveis": [u.username for u in livres],
        "logins_em_uso": [u.username for u in cand if u.id in ocupados],
    }


@transaction.atomic
def obter_login_historico_pap() -> Tuple[Optional["Usuario"], Optional[str]]:
    """
    Escolhe um login Diretoria livre do pool (chamar dentro de transaction.atomic
    junto com a criação da HistoricoPapBusca para evitar corrida).
    Retorna (usuario, None) ou (None, mensagem_erro).
    """
    from usuarios.models import Usuario

    ids = list(candidatos_historico_pap().values_list("id", flat=True))
    if not ids:
        return None, MSG_NENHUM_LOGIN

    locked = list(
        Usuario.objects.select_for_update()
        .filter(pk__in=ids)
        .order_by("username")
    )
    ocupados = ids_em_uso()
    livres = [u for u in locked if u.id not in ocupados and _tem_credencial(u)]
    if not livres:
        if not locked:
            return None, MSG_NENHUM_LOGIN
        return None, MSG_TODOS_EM_USO

    escolhido = livres[0]
    logger.info(
        "[POOL HIST PAP] Login %s reservado (matricula=%s)",
        escolhido.username,
        (escolhido.matricula_pap or "")[:12],
    )
    return escolhido, None
