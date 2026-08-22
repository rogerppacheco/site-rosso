"""Persistência dos contatos recusados pelo PAP na análise de crédito.

Mantido fora de `credito_pap_service` para que as regras de seleção de contato
continuem testáveis sem banco: o seletor recebe este repositório por injeção.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Iterable, Optional

from django.db import transaction
from django.db.models import F

logger = logging.getLogger(__name__)

Executor = Callable[[Callable[[], Any]], Any]

TIMEOUT_ORM_SEGUNDOS = 30


def executar_orm(funcao: Callable[[], Any], timeout: int = TIMEOUT_ORM_SEGUNDOS) -> Any:
    """
    Executa uma operação ORM mesmo quando a thread hospeda um event loop.

    A API sync do Playwright mantém um loop asyncio ativo e o Django recusa
    consultas nesse contexto; nesse caso a operação vai para uma thread limpa.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return funcao()

    resultado: list[Any] = [None]
    erro: list[Optional[BaseException]] = [None]

    def alvo() -> None:
        try:
            import django.db

            django.db.close_old_connections()
            resultado[0] = funcao()
        except BaseException as exc:  # noqa: BLE001 - repassado à chamadora
            erro[0] = exc

    thread = threading.Thread(target=alvo, name="credito-contato-orm", daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if erro[0] is not None:
        raise erro[0]
    if thread.is_alive():
        raise TimeoutError(f"Operação ORM expirou após {timeout}s")
    return resultado[0]


class RepositorioEmailsRecusadosPap:
    """Consulta e grava as recusas de e-mail da etapa 4 do PAP.

    Falhas de banco nunca interrompem a análise de crédito: o pior caso é o
    portal exibir o modal novamente e o fallback assumir na sequência.
    """

    def __init__(self, executor: Optional[Executor] = None) -> None:
        self._executor: Executor = executor or executar_orm

    def emails_recusados(self, emails: Iterable[str]) -> set[str]:
        candidatos = {
            str(email).strip().lower() for email in emails if str(email).strip()
        }
        if not candidatos:
            return set()
        try:
            return self._executor(lambda: self._buscar(candidatos))
        except Exception as erro:
            logger.warning("[CRÉDITO] Falha ao ler e-mails recusados: %s", erro)
            return set()

    def registrar_email(self, email: str, motivo: str) -> None:
        valor = str(email or "").strip().lower()
        if not valor:
            return
        try:
            self._executor(lambda: self._gravar(valor, motivo))
        except Exception as erro:
            logger.warning(
                "[CRÉDITO] Falha ao registrar e-mail recusado (%s): %s", valor, erro
            )

    @staticmethod
    def _buscar(candidatos: set[str]) -> set[str]:
        from crm_app.models import EmailRecusadoPapCredito

        return set(
            EmailRecusadoPapCredito.objects.filter(
                email__in=candidatos
            ).values_list("email", flat=True)
        )

    @staticmethod
    def _gravar(email: str, motivo: str) -> None:
        from crm_app.models import EmailRecusadoPapCredito

        with transaction.atomic():
            _, criado = EmailRecusadoPapCredito.objects.get_or_create(
                email=email,
                defaults={"motivo": motivo},
            )
            if not criado:
                EmailRecusadoPapCredito.objects.filter(email=email).update(
                    motivo=motivo,
                    ocorrencias=F("ocorrencias") + 1,
                )
