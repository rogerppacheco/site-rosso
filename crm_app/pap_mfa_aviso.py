"""Aviso no CRM quando o PAP espera aprovação no Microsoft Authenticator."""

from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import time

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


def _caminho_tela(chave: str) -> str:
    pasta = os.path.join(tempfile.gettempdir(), "pap_telas")
    os.makedirs(pasta, exist_ok=True)
    seguro = re.sub(r"[^A-Za-z0-9_-]", "", (chave or "").strip())[:80] or "pap"
    return os.path.join(pasta, seguro + ".jpg")


def publicar_tela_login(chave: str, imagem: bytes) -> None:
    """Guarda a foto da tela de aprovação para o modal da auditoria.

    O login roda na thread do Playwright. Gravar no cache do banco a partir
    dessa thread falha, então a foto vai para um arquivo no mesmo servidor.
    """
    if not (chave or "").strip() or not imagem:
        return
    caminho = _caminho_tela(chave)
    temporario = caminho + ".tmp"
    try:
        with open(temporario, "wb") as arquivo:
            arquivo.write(imagem)
        os.replace(temporario, caminho)
    except Exception as exc:
        logger.warning(
            "[PAP] Não foi possível guardar a tela de login (%s bytes): %s",
            len(imagem),
            type(exc).__name__,
        )


def obter_tela_login_b64(chave: str) -> str:
    if not (chave or "").strip():
        return ""
    caminho = _caminho_tela(chave)
    try:
        if not os.path.isfile(caminho):
            return ""
        if time.time() - os.path.getmtime(caminho) > _TTL_SEGUNDOS:
            return ""
        with open(caminho, "rb") as arquivo:
            return base64.b64encode(arquivo.read()).decode("ascii")
    except Exception as exc:
        logger.warning(
            "[PAP] Não foi possível ler a tela de login: %s",
            type(exc).__name__,
        )
        return ""


def limpar_tela_login(chave: str) -> None:
    if not (chave or "").strip():
        return
    caminho = _caminho_tela(chave)
    try:
        if os.path.isfile(caminho):
            os.remove(caminho)
    except Exception as exc:
        logger.warning(
            "[PAP] Não foi possível limpar a tela de login: %s",
            type(exc).__name__,
        )


def listar_avisos_mfa() -> list:
    try:
        dados = cache.get(_CHAVE) or {}
    except Exception:
        logger.warning("[PAP] Não foi possível ler os avisos de MFA no CRM.")
        return []
    return list(dados.values())
