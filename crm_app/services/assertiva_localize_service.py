"""Consulta cadastral na API Assertiva Localize para o fluxo de crédito."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from threading import Lock
from typing import Any, Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_DOCUMENTO_RE = re.compile(r"\D")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOKEN_LOCK = Lock()


class AssertivaError(Exception):
    """Erro esperado ao consultar ou interpretar a API Assertiva."""


class AssertivaConfigurationError(AssertivaError):
    """Credenciais ou configuração da integração ausentes."""


@dataclass(frozen=True)
class EnderecoAssertiva:
    """Endereço utilizável na consulta de viabilidade do PAP."""

    cep: str
    numero: str
    referencia: str
    logradouro: str = ""


@dataclass(frozen=True)
class DadosCreditoAssertiva:
    """Dados cadastrais selecionados para preencher o PAP."""

    telefones: tuple[str, ...]
    emails: tuple[str, ...]
    endereco: Optional[EnderecoAssertiva]

    @property
    def telefone_principal(self) -> Optional[str]:
        return self.telefones[0] if self.telefones else None

    @property
    def telefone_secundario(self) -> Optional[str]:
        return self.telefones[1] if len(self.telefones) > 1 else None

    @property
    def email_principal(self) -> Optional[str]:
        return self.emails[0] if self.emails else None


class AssertivaLocalizeService:
    """Cliente OAuth2 da API Assertiva Localize."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        http_session: Optional[requests.Session] = None,
    ) -> None:
        self.client_id = (
            client_id
            if client_id is not None
            else getattr(settings, "ASSERTIVA_CLIENT_ID", "")
        ).strip()
        self.client_secret = (
            client_secret
            if client_secret is not None
            else getattr(settings, "ASSERTIVA_CLIENT_SECRET", "")
        ).strip()
        self.timeout_seconds = timeout_seconds or int(
            getattr(settings, "ASSERTIVA_TIMEOUT_SECONDS", 20)
        )
        self.base_url = str(
            getattr(
                settings,
                "ASSERTIVA_API_BASE_URL",
                "https://api.assertivasolucoes.com.br",
            )
        ).rstrip("/")
        self.token_url = str(
            getattr(
                settings,
                "ASSERTIVA_TOKEN_URL",
                "https://api.assertivasolucoes.com.br/oauth2/v3/token",
            )
        )
        self.http = http_session or requests.Session()

    def consultar_para_credito(self, documento: str) -> DadosCreditoAssertiva:
        """Consulta CPF/CNPJ usando a finalidade LGPD de ciclo de crédito."""
        documento_limpo = _DOCUMENTO_RE.sub("", documento or "")
        if len(documento_limpo) not in (11, 14):
            raise AssertivaError("CPF/CNPJ inválido para consulta na Assertiva.")
        self._validar_configuracao()

        endpoint = "cpf" if len(documento_limpo) == 11 else "cnpj"
        try:
            payload = self._consultar_documento(endpoint, documento_limpo)
        except requests.RequestException as exc:
            logger.warning(
                "[ASSERTIVA] Falha de rede na consulta cadastral: %s",
                exc,
            )
            raise AssertivaError(
                "A Assertiva não respondeu dentro do tempo esperado."
            ) from exc
        resposta = payload.get("resposta")
        if not isinstance(resposta, dict):
            raise AssertivaError(
                "A Assertiva não retornou dados cadastrais para o documento."
            )

        return DadosCreditoAssertiva(
            telefones=self._selecionar_telefones(resposta),
            emails=self._selecionar_emails(resposta),
            endereco=self._selecionar_endereco(resposta),
        )

    def _validar_configuracao(self) -> None:
        if not self.client_id or not self.client_secret:
            raise AssertivaConfigurationError(
                "Credenciais da Assertiva não configuradas."
            )

    def _consultar_documento(
        self,
        endpoint: str,
        documento: str,
    ) -> dict[str, Any]:
        token = self._obter_token()
        response = self.http.get(
            f"{self.base_url}/localize/v3/{endpoint}",
            params={endpoint: documento, "idFinalidade": 2},
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        if response.status_code == 401:
            self._invalidar_token()
            token = self._obter_token()
            response = self.http.get(
                f"{self.base_url}/localize/v3/{endpoint}",
                params={endpoint: documento, "idFinalidade": 2},
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout_seconds,
            )
        return self._validar_resposta(response, "consulta cadastral")

    def _obter_token(self) -> str:
        cache_key = self._token_cache_key()
        token = cache.get(cache_key)
        if isinstance(token, str) and token:
            return token

        with _TOKEN_LOCK:
            token = cache.get(cache_key)
            if isinstance(token, str) and token:
                return token

            response = self.http.post(
                self.token_url,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
            payload = self._validar_resposta(response, "autenticação")
            token = str(payload.get("access_token") or "").strip()
            if not token:
                raise AssertivaError(
                    "A Assertiva autenticou, mas não retornou o token de acesso."
                )
            expires_in = max(int(payload.get("expires_in") or 60), 1)
            cache.set(cache_key, token, timeout=max(expires_in - 10, 1))
            return token

    def _invalidar_token(self) -> None:
        cache.delete(self._token_cache_key())

    def _token_cache_key(self) -> str:
        client_hash = hashlib.sha256(self.client_id.encode("utf-8")).hexdigest()[:16]
        return f"assertiva:oauth-token:{client_hash}"

    @staticmethod
    def _validar_resposta(
        response: requests.Response,
        operacao: str,
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AssertivaError(
                f"A Assertiva retornou uma resposta inválida na {operacao}."
            ) from exc

        if not response.ok:
            logger.warning(
                "[ASSERTIVA] Falha na %s: HTTP %s",
                operacao,
                response.status_code,
            )
            if response.status_code in (401, 403):
                raise AssertivaError(
                    "A Assertiva recusou as credenciais ou o acesso ao Localize."
                )
            if response.status_code == 422:
                raise AssertivaError(
                    "A Assertiva não conseguiu processar o documento informado."
                )
            raise AssertivaError(
                f"A consulta à Assertiva falhou (HTTP {response.status_code})."
            )
        if not isinstance(payload, dict):
            raise AssertivaError(
                f"A Assertiva retornou um formato inesperado na {operacao}."
            )
        return payload

    @classmethod
    def _selecionar_telefones(
        cls,
        resposta: dict[str, Any],
    ) -> tuple[str, ...]:
        grupos = resposta.get("telefones")
        if not isinstance(grupos, dict):
            return ()

        candidatos: list[tuple[int, int, str]] = []
        ordem = 0
        for tipo, peso_tipo in (("moveis", 100), ("fixos", 0)):
            itens = grupos.get(tipo)
            if not isinstance(itens, list):
                continue
            for item in itens:
                if not isinstance(item, dict):
                    continue
                numero = cls._normalizar_telefone(item.get("numero"))
                if not numero:
                    continue
                relacao = str(item.get("relacao") or "").strip().lower()
                aplicativos = item.get("aplicativos")
                aplicativos = aplicativos if isinstance(aplicativos, dict) else {}
                score = peso_tipo
                if relacao == "direto":
                    score += 50
                if aplicativos.get("whatsApp") or aplicativos.get("whatsAppBusiness"):
                    score += 30
                if item.get("naoPerturbe") is False:
                    score += 20
                candidatos.append((score, -ordem, numero))
                ordem += 1

        vistos: set[str] = set()
        selecionados: list[str] = []
        for _, _, numero in sorted(candidatos, reverse=True):
            if numero not in vistos:
                selecionados.append(numero)
                vistos.add(numero)
        return tuple(selecionados)

    @staticmethod
    def _normalizar_telefone(valor: Any) -> Optional[str]:
        numero = _DOCUMENTO_RE.sub("", str(valor or ""))
        if numero.startswith("55") and len(numero) in (12, 13):
            numero = numero[2:]
        return numero if len(numero) in (10, 11) else None

    @staticmethod
    def _selecionar_emails(resposta: dict[str, Any]) -> tuple[str, ...]:
        itens = resposta.get("emails")
        if not isinstance(itens, list):
            return ()
        emails: list[str] = []
        vistos: set[str] = set()
        for item in itens:
            valor = item.get("email") if isinstance(item, dict) else None
            email = str(valor or "").strip().lower()
            if _EMAIL_RE.match(email) and email not in vistos:
                emails.append(email)
                vistos.add(email)
        return tuple(emails)

    @staticmethod
    def _selecionar_endereco(
        resposta: dict[str, Any],
    ) -> Optional[EnderecoAssertiva]:
        itens = resposta.get("enderecos")
        if not isinstance(itens, list):
            return None

        candidatos: list[tuple[int, int, EnderecoAssertiva]] = []
        for ordem, item in enumerate(itens):
            if not isinstance(item, dict):
                continue
            cep = _DOCUMENTO_RE.sub("", str(item.get("cep") or ""))
            numero = str(item.get("numero") or "").strip()
            if len(cep) != 8 or not numero:
                continue
            precisao = str(item.get("precisaoCep") or "").strip().upper()
            complemento = str(item.get("complemento") or "").strip()
            logradouro = str(item.get("logradouro") or "").strip()
            referencia = complemento or "Endereço cadastral do cliente"
            score = 100 if precisao == "CONFIRMADA" else 0
            if logradouro:
                score += 10
            candidatos.append(
                (
                    score,
                    -ordem,
                    EnderecoAssertiva(
                        cep=cep,
                        numero=numero,
                        referencia=referencia[:100],
                        logradouro=logradouro,
                    ),
                )
            )
        if not candidatos:
            return None
        return max(candidatos, key=lambda candidato: (candidato[0], candidato[1]))[2]
