"""Aviso no CRM quando o PAP espera aprovação no Microsoft Authenticator."""

from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

_CHAVE = "pap_mfa_avisos_v1"
_TTL_SEGUNDOS = 180


def mensagem_aviso_mfa(matricula: str, numero: str = "") -> str:
    tt = (matricula or "").strip() or "PAP"
    texto = (
        f"O PAP pediu aprovação no Microsoft Authenticator para {tt}. "
        "Abra o celular e aprove a entrada. O sistema segue sozinho quando a aprovação entrar."
    )
    numero_limpo = (numero or "").strip()
    if numero_limpo:
        texto += f" Número para digitar no aplicativo: {numero_limpo}."
    return texto


def usuario_ve_aviso_mfa(user) -> bool:
    """BO com senha do PAP, ou equipe interna, já logado no CRM."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    return bool(str(getattr(user, "senha_pap", "") or "").strip())


def publicar_aviso_mfa(matricula: str, numero: str = "") -> None:
    tt = (matricula or "").strip()
    if not tt:
        return
    try:
        dados = cache.get(_CHAVE) or {}
        dados[tt] = {
            "matricula": tt,
            "numero": (numero or "").strip(),
            "mensagem": mensagem_aviso_mfa(tt, numero),
        }
        cache.set(_CHAVE, dados, _TTL_SEGUNDOS)
    except Exception:
        logger.warning("[PAP] Não foi possível publicar o aviso de MFA no CRM.")


def limpar_aviso_mfa(matricula: str = "") -> None:
    tt = (matricula or "").strip()
    try:
        if not tt:
            cache.delete(_CHAVE)
            return
        dados = cache.get(_CHAVE) or {}
        dados.pop(tt, None)
        if dados:
            cache.set(_CHAVE, dados, _TTL_SEGUNDOS)
        else:
            cache.delete(_CHAVE)
    except Exception:
        logger.warning("[PAP] Não foi possível limpar o aviso de MFA no CRM.")


def listar_avisos_mfa() -> list:
    try:
        dados = cache.get(_CHAVE) or {}
    except Exception:
        logger.warning("[PAP] Não foi possível ler os avisos de MFA no CRM.")
        return []
    return list(dados.values())
