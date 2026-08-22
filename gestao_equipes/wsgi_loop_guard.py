"""
Isola o WSGI de threads com event loop asyncio ativo.

A API síncrona do Playwright (greenlets) deixa um loop rodando na OS thread.
O Django 3.1+ recusa ORM nesse contexto (SynchronousOnlyOperation) — o primeiro
hit é o JWT (`simplejwt` busca o usuário) e a API inteira devolve 500.

Gunicorn usa `--threads`; se o Playwright rodou na mesma thread de um request
(renovação de token Nio, inclusão, etc.), os próximos requests daquela thread
quebram. Este wrapper detecta o loop e executa o app numa thread limpa.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

StartResponse = Callable[..., Any]
WsgiApp = Callable[[dict, StartResponse], Iterable[bytes]]

TIMEOUT_WSGI_SEGUNDOS = 1200


def thread_tem_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class WsgiLoopGuard:
    def __init__(self, app: WsgiApp, timeout_seconds: int = TIMEOUT_WSGI_SEGUNDOS) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    def __call__(self, environ: dict, start_response: StartResponse) -> Iterable[bytes]:
        if not thread_tem_event_loop():
            return self.app(environ, start_response)

        metodo = environ.get("REQUEST_METHOD", "?")
        path = environ.get("PATH_INFO", "")
        logger.error(
            "Thread HTTP com event loop ativo (Playwright). Isolando %s %s",
            metodo,
            path,
        )
        return _executar_wsgi_em_thread_limpa(
            self.app,
            environ,
            start_response,
            timeout_seconds=self.timeout_seconds,
        )


def _executar_wsgi_em_thread_limpa(
    app: WsgiApp,
    environ: dict,
    start_response: StartResponse,
    *,
    timeout_seconds: int,
) -> List[bytes]:
    resultado: dict[str, Any] = {}
    erro: list[Optional[BaseException]] = [None]

    def alvo() -> None:
        try:
            captured: list[Tuple[str, Sequence[Tuple[str, str]], Any]] = []

            def sr(status: str, headers: Sequence[Tuple[str, str]], exc_info=None):
                captured.append((status, headers, exc_info))
                return lambda _chunk: None

            body = list(app(environ, sr))
            resultado["captured"] = captured
            resultado["body"] = body
        except BaseException as exc:  # noqa: BLE001 - repassado à thread HTTP
            erro[0] = exc

    thread = threading.Thread(target=alvo, name="wsgi-sync-clean", daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if erro[0] is not None:
        raise erro[0]
    if thread.is_alive():
        raise TimeoutError(
            f"Request isolado do event loop expirou após {timeout_seconds}s"
        )

    captured = resultado.get("captured") or []
    if not captured:
        start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
        return [b"WSGI isolado sem start_response"]

    status, headers, exc_info = captured[-1]
    if exc_info:
        start_response(status, list(headers), exc_info)
    else:
        start_response(status, list(headers))
    return list(resultado.get("body") or [])
