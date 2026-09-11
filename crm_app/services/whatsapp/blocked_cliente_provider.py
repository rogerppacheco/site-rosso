"""Provider nulo: envio a cliente bloqueado até o número Meta (Cloud API) estar ativo."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from crm_app.services.whatsapp.base import WhatsAppProvider

logger = logging.getLogger(__name__)

CODIGO_BLOQUEIO = "CANAL_CLIENTE_BLOQUEADO"
MSG_CANAL_CLIENTE_BLOQUEADO = (
    "Envios a clientes só podem sair pelo número oficial do plano registrado na Meta. "
    "Esse número ainda não está configurado ou não foi ativado na aba WhatsApp. "
    "O número do time comercial não envia mensagens a clientes."
)


class ClienteCanalBloqueadoProvider(WhatsAppProvider):
    """Recusa qualquer outbound para cliente final (não usa Z-API / número comercial)."""

    def _falha(self, telefone: str = "") -> Tuple[bool, Dict[str, str]]:
        logger.warning("[WhatsApp] %s dest=%s", MSG_CANAL_CLIENTE_BLOQUEADO, telefone or "-")
        return False, {"error": MSG_CANAL_CLIENTE_BLOQUEADO, "code": CODIGO_BLOQUEIO}

    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        return None

    def enviar_mensagem_texto_raw(self, telefone: str, mensagem: str) -> Tuple[bool, Any]:
        ok, resp = self._falha(telefone)
        return ok, resp

    def enviar_mensagem_com_botoes_reply(
        self,
        telefone: str,
        mensagem: str,
        button_actions: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        return self._falha(telefone)

    def enviar_lista_opcoes(
        self,
        telefone: str,
        mensagem: str,
        opcoes: List[Dict[str, str]],
        titulo_lista: str = "Opções",
        botao_label: str = "Ver opções",
    ) -> Tuple[bool, Any]:
        return self._falha(telefone)

    def enviar_template(
        self,
        telefone: str,
        template_name: str,
        language_code: str = "pt_BR",
        body_params=None,
        template_params=None,
    ) -> Tuple[bool, Any]:
        return self._falha(telefone)

    def enviar_imagem_b64(self, telefone: str, img_b64: str, caption: str = "") -> Optional[Dict[str, Any]]:
        self._falha(telefone)
        return None

    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        self._falha(telefone)
        return False

    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        self._falha(telefone)
        return False

    def listar_grupos(self) -> List[Dict[str, str]]:
        return []
