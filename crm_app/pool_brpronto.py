# crm_app/pool_brpronto.py
"""
Pool de logins Br Pronto PDV (ged360) para consulta de biometria.

Somente contas com brpronto_login + brpronto_senha e
brpronto_disponivel_para_automacao=True entram no pool.
O GED bloqueia sessão simultânea — o serviço sempre faz logoff; o lock
evita dois jobs usarem o mesmo login ao mesmo tempo.
"""
from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_MINUTOS = 15

MSG_TODOS_BRPRONTO_EM_USO = (
    "⚠️ *Todos os logins Br Pronto estão em uso*\n\n"
    "Aguarde alguns minutos e tente novamente.\n\n"
    "Digite *BIO* para tentar de novo."
)

MSG_NENHUM_BRPRONTO = (
    "⚠️ *Nenhum login Br Pronto liberado para automação*\n\n"
    "Cadastre Login/Senha Br Pronto no usuário e marque "
    "*Disponibilizar login Br Pronto para o bot* na Governança."
)


def _limpar_locks_expirados() -> int:
    from crm_app.models import BrProntoBoEmUso

    limite = timezone.now() - timedelta(minutes=LOCK_TIMEOUT_MINUTOS)
    deletados = BrProntoBoEmUso.objects.filter(locked_at__lt=limite).delete()
    if deletados[0] > 0:
        logger.info("[POOL BrPronto] Liberados %s lock(s) expirado(s)", deletados[0])
    return deletados[0]


def obter_login_brpronto(
    solicitante_telefone: str = "",
    sessao_whatsapp_id: Optional[int] = None,
    origem: str = "bio",
) -> Tuple[Optional["Usuario"], Optional[str]]:
    """
    Obtém um login Br Pronto disponível (randômico entre livres).

    Returns:
        (usuario, None) em sucesso
        (None, mensagem_erro) quando indisponível
    """
    from usuarios.models import Usuario
    from crm_app.models import BrProntoBoEmUso

    _limpar_locks_expirados()

    ids_em_uso = set(BrProntoBoEmUso.objects.values_list("bo_usuario_id", flat=True))

    qs = (
        Usuario.objects.filter(
            is_active=True,
            brpronto_disponivel_para_automacao=True,
        )
        .exclude(brpronto_login__isnull=True)
        .exclude(brpronto_login="")
        .exclude(brpronto_senha__isnull=True)
        .exclude(brpronto_senha="")
    )
    if ids_em_uso:
        qs = qs.exclude(id__in=ids_em_uso)

    candidatos = list(qs)
    if not candidatos:
        # Distinguir: ninguém cadastrado vs todos em uso
        total_cfg = (
            Usuario.objects.filter(
                is_active=True,
                brpronto_disponivel_para_automacao=True,
            )
            .exclude(brpronto_login__isnull=True)
            .exclude(brpronto_login="")
            .exclude(brpronto_senha__isnull=True)
            .exclude(brpronto_senha="")
            .count()
        )
        if total_cfg == 0:
            return None, MSG_NENHUM_BRPRONTO
        return None, MSG_TODOS_BRPRONTO_EM_USO

    random.shuffle(candidatos)
    for bo in candidatos:
        try:
            with transaction.atomic():
                BrProntoBoEmUso.objects.create(
                    bo_usuario=bo,
                    solicitante_telefone=solicitante_telefone or "",
                    sessao_whatsapp_id=sessao_whatsapp_id,
                    origem=origem or "",
                )
            logger.info(
                "[POOL BrPronto] %s (login=%s) alocado para %s origem=%s",
                bo.username,
                bo.brpronto_login,
                solicitante_telefone or "sistema",
                origem,
            )
            return bo, None
        except Exception as e:
            logger.debug("[POOL BrPronto] BO %s indisponível: %s", bo.id, e)
            continue

    return None, MSG_TODOS_BRPRONTO_EM_USO


def liberar_login_brpronto(
    bo_usuario_id: int,
    solicitante_telefone: str = "",
) -> bool:
    """Libera o lock do login Br Pronto após a consulta."""
    from crm_app.models import BrProntoBoEmUso

    try:
        qs = BrProntoBoEmUso.objects.filter(bo_usuario_id=bo_usuario_id)
        if solicitante_telefone:
            qs = qs.filter(solicitante_telefone=solicitante_telefone)
        n, _ = qs.delete()
        if n:
            logger.info(
                "[POOL BrPronto] Liberado bo_id=%s telefone=%s",
                bo_usuario_id,
                solicitante_telefone or "-",
            )
        return n > 0
    except Exception as e:
        logger.exception("[POOL BrPronto] Erro ao liberar: %s", e)
        return False


def liberar_todos_brpronto() -> Tuple[int, str]:
    """Libera todos os locks Br Pronto (painel / emergência)."""
    from crm_app.models import BrProntoBoEmUso

    try:
        total = BrProntoBoEmUso.objects.count()
        if total == 0:
            return 0, "Nenhum login Br Pronto estava em uso."
        BrProntoBoEmUso.objects.all().delete()
        return total, f"Liberados {total} login(s) Br Pronto."
    except Exception as e:
        logger.exception("[POOL BrPronto] Erro ao liberar todos: %s", e)
        return 0, f"Erro ao liberar: {e}"
