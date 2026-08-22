"""Detecção do banner 'Sua senha expirou' no IdP V.tal."""

from __future__ import annotations

from django.test import SimpleTestCase

from crm_app.services_pap_nio import PAPNioAutomation


class FakePageSenhaExpirada:
    def __init__(self, html: str) -> None:
        self._html = html
        self.url = "https://login.vtal.com/nidp/saml2/sso"

    def content(self) -> str:
        return self._html

    def inner_text(self, _sel: str) -> str:
        return self._html

    def get_by_text(self, _pattern):  # pragma: no cover - fallback HTML cobre o caso
        class _Loc:
            def count(self) -> int:
                return 0

        return _Loc()


class PAPSenhaExpiradaTests(SimpleTestCase):
    def test_detecta_banner_sua_senha_expirou(self) -> None:
        pap = PAPNioAutomation("TT190343", "x")
        pap.page = FakePageSenhaExpirada(
            '<div class="alert">Sua senha expirou.</div><input id="inputMatricula">'
        )
        self.assertTrue(pap._pagina_senha_expirada())
        self.assertTrue(pap._pagina_tem_erro_login())

    def test_mensagem_inclui_matricula(self) -> None:
        pap = PAPNioAutomation("TT190343", "x")
        msg = pap._mensagem_senha_pap_expirada()
        self.assertIn("TT190343", msg)
        self.assertIn("expirada", msg.lower())

    def test_nao_detecta_sem_banner(self) -> None:
        pap = PAPNioAutomation("TT190343", "x")
        pap.page = FakePageSenhaExpirada("<div>EFETUAR LOGIN</div><input id='inputMatricula'>")
        self.assertFalse(pap._pagina_senha_expirada())
