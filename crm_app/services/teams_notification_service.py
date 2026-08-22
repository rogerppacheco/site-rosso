"""Notificações Microsoft Teams via n8n (outbound, fire-and-forget)."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TeamsNotificationService:
    """
    Envia mensagens ao Teams postando JSON no webhook n8n.
    O n8n formata o MessageCard e encaminha ao Incoming Webhook do canal.
    """

    def __init__(self) -> None:
        self.webhook_url = self._resolve_webhook_url()

    @staticmethod
    def _resolve_webhook_url() -> str:
        for key in ("N8N_TEAMS_WEBHOOK_URL", "TEAMS_N8N_WEBHOOK_URL"):
            val = getattr(settings, key, None) or os.environ.get(key, "")
            if val and str(val).strip():
                return str(val).strip()
        return ""

    @property
    def configurado(self) -> bool:
        return bool(self.webhook_url)

    def enviar_mensagem(
        self,
        *,
        titulo: str,
        texto: str,
        source: str,
        image_url: Optional[str] = None,
        timeout: int = 15,
    ) -> Tuple[bool, Any]:
        """
        Dispara notificação ao Teams. Não levanta exceção — retorna (ok, detalhe).
        """
        if not self.webhook_url:
            return False, "N8N_TEAMS_WEBHOOK_URL não configurada"

        titulo_limpo = (titulo or "").strip() or "Site Record"
        texto_limpo = (texto or "").strip()
        if not texto_limpo:
            return False, "texto vazio"

        payload: dict[str, Any] = {
            "title": titulo_limpo,
            "text": texto_limpo,
            "source": (source or "site-record").strip(),
        }
        img = (image_url or "").strip()
        if img:
            payload["image_url"] = img

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            if resp.status_code in (200, 201, 202, 204):
                try:
                    body = resp.json() if resp.content else {}
                except ValueError:
                    body = {"status": resp.status_code}
                return True, body
            logger.error(
                "[Teams n8n] HTTP %s: %s",
                resp.status_code,
                resp.text[:500],
            )
            return False, resp.text[:500]
        except requests.exceptions.RequestException as exc:
            logger.error("[Teams n8n] Request failed: %s", exc)
            return False, str(exc)


def teams_notificacao_habilitada() -> bool:
    """Teams ativo na config e webhook n8n definido."""
    from crm_app.models import AnteciparInstalacaoConfig

    config = AnteciparInstalacaoConfig.objects.first()
    if not config or not config.teams_notificacao_ativo:
        return False
    return TeamsNotificationService().configurado


def media_url_absoluta(caminho_relativo: Optional[str]) -> Optional[str]:
    """Monta URL pública absoluta para arquivo em MEDIA (quando acessível)."""
    if not caminho_relativo:
        return None
    rel = str(caminho_relativo).lstrip("/")
    if not rel:
        return None
    base = (getattr(settings, "SITE_URL", None) or "").rstrip("/")
    if not base:
        return None
    media_prefix = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").strip("/")
    return f"{base}/{media_prefix}/{rel}"


def enviar_teams_operacional(
    *,
    titulo: str,
    texto: str,
    source: str,
    image_url: Optional[str] = None,
) -> Tuple[bool, Any]:
    """
    Envia ao Teams se habilitado na config. Falha silenciosa (log + retorno).
    """
    if not teams_notificacao_habilitada():
        return False, "Teams desativado ou webhook não configurado"
    ok, detalhe = TeamsNotificationService().enviar_mensagem(
        titulo=titulo,
        texto=texto,
        source=source,
        image_url=image_url,
    )
    if not ok:
        logger.warning("[Teams] Falha (%s): %s", source, detalhe)
    return ok, detalhe
