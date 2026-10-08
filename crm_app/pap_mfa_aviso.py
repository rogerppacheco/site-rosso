"""Aviso no CRM quando o PAP espera aprovação no Microsoft Authenticator."""

from __future__ import annotations

import base64
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


def _chave_tela(chave: str) -> str:
    return f"pap_tela_login:{(chave or '').strip()}"


def publicar_tela_login(chave: str, imagem: bytes) -> None:
    """Guarda a foto da tela de aprovação para o modal da auditoria."""
    if not (chave or "").strip() or not imagem:
        return
    try:
        cache.set(
            _chave_tela(chave),
            base64.b64encode(imagem).decode("ascii"),
            _TTL_SEGUNDOS,
        )
    except Exception:
        logger.warning("[PAP] Não foi possível guardar a tela de login.")


def obter_tela_login_b64(chave: str) -> str:
    if not (chave or "").strip():
        return ""
    try:
        return cache.get(_chave_tela(chave)) or ""
    except Exception:
        logger.warning("[PAP] Não foi possível ler a tela de login.")
        return ""


def limpar_tela_login(chave: str) -> None:
    if not (chave or "").strip():
        return
    try:
        cache.delete(_chave_tela(chave))
    except Exception:
        logger.warning("[PAP] Não foi possível limpar a tela de login.")


def listar_avisos_mfa() -> list:
    try:
        dados = cache.get(_CHAVE) or {}
    except Exception:
        logger.warning("[PAP] Não foi possível ler os avisos de MFA no CRM.")
        return []
    return list(dados.values())
