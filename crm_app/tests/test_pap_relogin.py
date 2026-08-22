from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from django.test import SimpleTestCase

from crm_app.services_pap_nio import PAPNioAutomation


class FakePage:
    def __init__(self) -> None:
        self.url = "https://pap.niointernet.com.br/"
        self.goto_calls: list[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    def goto(self, url: str, **kwargs: Any) -> None:
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, timeout: int) -> None:
        self.last_wait = timeout


class FakeContext:
    def __init__(self) -> None:
        self.page = FakePage()
        self.closed = False
        self.storage_paths: list[str] = []

    def close(self) -> None:
        self.closed = True

    def new_page(self) -> FakePage:
        return self.page

    def storage_state(self, *, path: str) -> None:
        self.storage_paths.append(path)


class FakeBrowser:
    def __init__(self) -> None:
        self.new_context_calls: list[dict[str, Any]] = []
        self.new_context_result = FakeContext()
        self.closed = False

    def new_context(self, **kwargs: Any) -> FakeContext:
        self.new_context_calls.append(kwargs)
        return self.new_context_result

    def close(self) -> None:
        self.closed = True


class PAPReloginTests(SimpleTestCase):
    def test_relogin_descarta_contexto_com_cookies_expirados(self) -> None:
        pap = PAPNioAutomation("matricula", "senha")
        contexto_antigo = FakeContext()
        pagina_antiga = contexto_antigo.page
        browser = FakeBrowser()
        pap.browser = browser  # type: ignore[assignment]
        pap.context = contexto_antigo  # type: ignore[assignment]
        pap.page = pagina_antiga  # type: ignore[assignment]
        pap._fechar_modal_sessao_expirada = Mock()  # type: ignore[method-assign]
        pap._aguardar_pagina_estavel = Mock()  # type: ignore[method-assign]
        pap._fazer_login = Mock(  # type: ignore[method-assign]
            return_value=(True, "Login realizado")
        )
        pap._sessao_pap_autenticada = Mock(  # type: ignore[method-assign]
            return_value=True
        )
        pap._esta_no_idp_vtal = Mock(return_value=False)  # type: ignore[method-assign]

        sucesso, mensagem = pap._relogin_pap(
            "https://pap.niointernet.com.br/administrativo/consulta-os"
        )

        self.assertTrue(sucesso)
        self.assertEqual(mensagem, "Sessão restaurada com sucesso.")
        self.assertTrue(pagina_antiga.closed)
        self.assertTrue(contexto_antigo.closed)
        self.assertEqual(len(browser.new_context_calls), 1)
        self.assertNotIn("storage_state", browser.new_context_calls[0])
        self.assertIs(pap.page, browser.new_context_result.page)
        self.assertEqual(
            browser.new_context_result.page.goto_calls,
            [
                "https://pap.niointernet.com.br/",
                "https://pap.niointernet.com.br/administrativo/consulta-os",
            ],
        )

    def test_fechar_sessao_preserva_storage_sem_logout(self) -> None:
        pap = PAPNioAutomation("matricula", "senha")
        contexto = FakeContext()
        pap.browser = FakeBrowser()  # type: ignore[assignment]
        pap.context = contexto  # type: ignore[assignment]
        pap.page = contexto.page  # type: ignore[assignment]
        pap.sessao_iniciada = True
        pap._pap_slot_held = False
        pap._clicar_sair = Mock(return_value=True)  # type: ignore[method-assign]
        pap._invalidar_storage_state = Mock()  # type: ignore[method-assign]
        pap._sessao_pap_autenticada = Mock(return_value=True)  # type: ignore[method-assign]

        pap._fechar_sessao()

        pap._clicar_sair.assert_not_called()
        pap._invalidar_storage_state.assert_not_called()
        self.assertEqual(contexto.storage_paths, [pap.storage_state_path])

    def test_fechar_sessao_nao_persiste_storage_apos_logout(self) -> None:
        pap = PAPNioAutomation("matricula", "senha")
        contexto = FakeContext()
        pap.browser = FakeBrowser()  # type: ignore[assignment]
        pap.context = contexto  # type: ignore[assignment]
        pap.page = contexto.page  # type: ignore[assignment]
        pap.sessao_iniciada = True
        pap._pap_slot_held = False
        pap._clicar_sair = Mock(return_value=True)  # type: ignore[method-assign]
        pap._invalidar_storage_state = Mock()  # type: ignore[method-assign]
        pap._sessao_pap_autenticada = Mock(return_value=False)  # type: ignore[method-assign]

        pap._fechar_sessao(fazer_logout=True)

        pap._clicar_sair.assert_called_once()
        pap._invalidar_storage_state.assert_called_once()
        self.assertEqual(contexto.storage_paths, [])
