"""Garante que requests HTTP sobrevivem a thread com event loop do Playwright."""
from __future__ import annotations

import asyncio
import threading
import unittest

from gestao_equipes.wsgi_loop_guard import WsgiLoopGuard, thread_tem_event_loop


def _app_eco(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [f"{threading.current_thread().name}".encode()]


class WsgiLoopGuardTests(unittest.TestCase):
    def test_thread_sem_event_loop(self) -> None:
        self.assertFalse(thread_tem_event_loop())

    def test_guard_nao_isola_sem_loop(self) -> None:
        guard = WsgiLoopGuard(_app_eco)
        capturado: list[str] = []

        def sr(status, headers, exc_info=None):
            capturado.append(status)

        body = b"".join(guard({"PATH_INFO": "/", "REQUEST_METHOD": "GET"}, sr))
        self.assertEqual(capturado, ["200 OK"])
        self.assertEqual(body.decode(), threading.current_thread().name)

    def test_guard_isola_quando_ha_loop(self) -> None:
        guard = WsgiLoopGuard(_app_eco)
        atual = threading.current_thread().name

        async def dentro_do_loop() -> bytes:
            capturado: list[str] = []

            def sr(status, headers, exc_info=None):
                capturado.append(status)

            corpo = b"".join(
                guard({"PATH_INFO": "/api/crm/vendas/", "REQUEST_METHOD": "GET"}, sr)
            )
            self.assertEqual(capturado, ["200 OK"])
            return corpo

        body = asyncio.run(dentro_do_loop())
        self.assertNotEqual(body.decode(), atual)
        self.assertEqual(body.decode(), "wsgi-sync-clean")
