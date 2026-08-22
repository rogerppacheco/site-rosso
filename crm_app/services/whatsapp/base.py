"""Contrato dos providers WhatsApp (Z-API / Evolution / WhatsAtende)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class WhatsAppProvider(ABC):
    @abstractmethod
    def verificar_numero_existe(self, telefone: str) -> Optional[bool]:
        """True/False se tem WhatsApp; None se não foi possível verificar."""

    @abstractmethod
    def enviar_mensagem_texto_raw(
        self, telefone: str, mensagem: str
    ) -> Tuple[bool, Any]:
        ...

    @abstractmethod
    def enviar_mensagem_com_botoes_reply(
        self,
        telefone: str,
        mensagem: str,
        button_actions: List[Dict[str, Any]],
        title: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        ...

    def enviar_lista_opcoes(
        self,
        telefone: str,
        mensagem: str,
        opcoes: List[Dict[str, str]],
        titulo_lista: str = "Opções",
        botao_label: str = "Ver opções",
    ) -> Tuple[bool, Any]:
        """Lista interativa (Z-API option list). Default: não suportado."""
        return False, None

    @abstractmethod
    def enviar_imagem_b64(
        self, telefone: str, img_b64: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def enviar_pdf_url(
        self,
        telefone: str,
        pdf_url: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        ...

    @abstractmethod
    def enviar_pdf_b64(
        self,
        telefone: str,
        base64_data: str,
        nome_arquivo: str = "extrato.pdf",
        caption: Optional[str] = None,
    ) -> bool:
        ...

    @abstractmethod
    def listar_grupos(self) -> List[Dict[str, str]]:
        ...

    def resposta_indica_sucesso(self, resp: Any) -> bool:
        if not resp or not isinstance(resp, dict):
            return False
        if resp.get("error"):
            return False
        return bool(
            resp.get("messageId")
            or resp.get("zaapId")
            or resp.get("id")
            or resp.get("key")
            or resp.get("status") == "PENDING"
        )
