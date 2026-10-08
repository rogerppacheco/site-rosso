"""Login Microsoft do PAP: uma senha, aviso ao BO, sem nova tentativa."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

from crm_app.pap_login_microsoft import (
    classificar_tela_microsoft,
    email_acesso_microsoft,
    extrair_numero_mfa,
)
from crm_app.pap_mfa_aviso import (
    limpar_aviso_mfa,
    limpar_tela_login,
    listar_avisos_mfa,
    mensagem_aviso_mfa,
    obter_tela_login_b64,
    publicar_aviso_mfa,
    publicar_tela_login,
    usuario_ve_aviso_mfa,
)
from crm_app.pap_mfa_aviso_api import pap_mfa_pendente_view
from crm_app.services_pap_nio import PAPNioAutomation

_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pap-mfa-testes",
    }
}


class EmailMicrosoftTests(SimpleTestCase):
    def test_coloca_matricula_antes_do_arroba(self) -> None:
        self.assertEqual(
            email_acesso_microsoft("TT123456"),
            "TT123456@vtalcorp.onmicrosoft.com",
        )

    def test_nao_duplica_dominio(self) -> None:
        self.assertEqual(
            email_acesso_microsoft("TT123456@vtalcorp.onmicrosoft.com"),
            "TT123456@vtalcorp.onmicrosoft.com",
        )


class ClassificarTelaTests(SimpleTestCase):
    def test_senha_oculta_na_primeira_tela_nao_conta(self) -> None:
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto="Sign in\nEmail, phone, or Skype",
            email_visivel=True,
            senha_visivel=False,
        )
        self.assertEqual(estado, "email")

    def test_campo_de_senha_no_html_nao_pula_o_email(self) -> None:
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto=(
                "Entrar\n"
                "Insira um endereço de email, número de telefone ou nome Skype válido.\n"
                "Avançar"
            ),
            email_visivel=True,
            senha_visivel=True,
        )
        self.assertEqual(estado, "email")

    def test_manter_conectado(self) -> None:
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto="Permanecer conectado?\nManter conectado",
            email_visivel=False,
            senha_visivel=False,
        )
        self.assertEqual(estado, "kmsi")

    def test_continuar_conectado_e_a_mesma_pergunta(self) -> None:
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto=(
                "Continuar conectado?\n"
                "Faça isso para reduzir o número de vezes que será solicitado a entrar.\n"
                "Não mostrar isso novamente"
            ),
            email_visivel=False,
            senha_visivel=False,
        )
        self.assertEqual(estado, "kmsi")

    def test_numero_do_authenticator(self) -> None:
        texto = "Aprovar uma solicitação\n82"
        self.assertEqual(extrair_numero_mfa(texto), "82")
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto=texto,
            email_visivel=False,
            senha_visivel=False,
        )
        self.assertEqual(estado, "mfa")

    def test_senha_recusada_interrompe(self) -> None:
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto="Your account or password is incorrect",
            email_visivel=False,
            senha_visivel=True,
        )
        self.assertEqual(estado, "erro_credencial")

    def test_qr_code_de_cadastro_nao_e_aprovacao(self) -> None:
        estado = classificar_tela_microsoft(
            url="https://login.microsoftonline.com/tenant/saml2",
            texto="Mantenha sua conta segura\nEscaneie o código QR",
            email_visivel=False,
            senha_visivel=False,
        )
        self.assertEqual(estado, "cadastro")


class _CaixaNaoMostrar:
    def __init__(self) -> None:
        self.marcado = False
        self.eventos: list[str] = []

    def is_visible(self) -> bool:
        return True

    def is_checked(self) -> bool:
        return self.marcado

    def check(self) -> None:
        self.marcado = True
        self.eventos.append("marcou")


class _Campo:
    def __init__(self, visivel: bool, texto: str = "") -> None:
        self._visivel = visivel
        self._texto = texto

    def is_visible(self) -> bool:
        return self._visivel

    def inner_text(self) -> str:
        return self._texto

    def is_checked(self) -> bool:
        return False

    def check(self) -> None:
        return None


class _PaginaMicrosoft:
    def __init__(self) -> None:
        self.url = "https://login.microsoftonline.com/tenant/saml2"
        self.texto = "Sign in"
        self.email_visivel = True
        self.senha_visivel = False
        self.fills: list[tuple[str, str]] = []
        self.valores: dict[str, str] = {}
        self.clicks: list[str] = []
        self.fase = "email"
        self._esperas_mfa = 0
        self.caixa_nao_mostrar = None
        self.avaliou_nao_mostrar = False

    def inner_text(self, _seletor: str) -> str:
        return self.texto

    def query_selector(self, seletor: str):
        if seletor == 'input[name="loginfmt"]':
            return _Campo(self.email_visivel)
        if seletor == 'input[name="passwd"]':
            return _Campo(self.senha_visivel)
        if seletor == "#idRichContext_DisplaySign":
            return None
        if seletor == "#KmsiCheckboxField":
            return self.caixa_nao_mostrar
        if seletor == "input[name='DontShowAgain']":
            return None
        return None

    def evaluate(self, _script: str):
        self.avaliou_nao_mostrar = True
        return True

    def fill(self, seletor: str, valor: str, timeout: int = 0) -> None:
        self.fills.append((seletor, valor))
        self.valores[seletor] = valor
        if "passwd" in seletor and self.fase == "erro":
            return None

    def input_value(self, seletor: str) -> str:
        return self.valores.get(seletor, "")

    def click(self, seletor: str, timeout: int = 0) -> None:
        self.clicks.append(seletor)
        if self.fase == "email" and seletor == "#idSIButton9":
            self.fase = "senha"
            self.texto = "Enter password"
            self.email_visivel = False
            self.senha_visivel = True
            return None
        if self.fase == "senha" and seletor == "#idSIButton9":
            self.fase = "mfa"
            self.texto = "Approve a request on Microsoft Authenticator\n82"
            self.senha_visivel = False
            return None
        if self.fase == "erro" and seletor == "#idSIButton9":
            self.texto = "Your account or password is incorrect"
            self.senha_visivel = True
            return None
        if self.fase == "kmsi" and seletor == "#idSIButton9":
            self.url = "https://pap.niointernet.com.br/administrativo/novo-pedido"
            self.texto = "Novo pedido"
            return None

    def wait_for_timeout(self, _timeout: int) -> None:
        if self.fase != "mfa":
            return None
        self._esperas_mfa += 1
        if self._esperas_mfa >= 2:
            self.url = "https://pap.niointernet.com.br/administrativo/consulta-os"
            self.texto = "Consulta"
            self.fase = "pap"


@override_settings(CACHES=_CACHE)
class LoginMicrosoftSemRepetirSenhaTests(SimpleTestCase):
    def tearDown(self) -> None:
        limpar_aviso_mfa()

    def test_uma_senha_aviso_e_reconhece_aprovacao(self) -> None:
        pap = PAPNioAutomation("TT123456", "senha-teste")
        pap.page = _PaginaMicrosoft()  # type: ignore[assignment]
        pap._capture_screenshot = Mock()  # type: ignore[method-assign]
        pap._mfa_espera_segundos = 5

        ok, msg = pap._fazer_login_microsoft()

        self.assertTrue(ok)
        self.assertIn("sucesso", msg.lower())
        senhas = [valor for seletor, valor in pap.page.fills if "passwd" in seletor]
        self.assertEqual(senhas, ["senha-teste"])
        self.assertEqual(
            [valor for seletor, valor in pap.page.fills if "loginfmt" in seletor],
            ["TT123456@vtalcorp.onmicrosoft.com"],
        )
        self.assertNotIn("#idBtn_Back", pap.page.clicks)
        self.assertEqual(listar_avisos_mfa(), [])
        pap._capture_screenshot.assert_called()

    def test_campo_senha_visivel_no_email_nao_aperta_avancar_vazio(self) -> None:
        pagina = _PaginaMicrosoft()
        pagina.senha_visivel = True
        pagina.texto = "Entrar\nEmail, telefone ou Skype"
        pap = PAPNioAutomation("TT398861", "senha-teste")
        pap.page = pagina  # type: ignore[assignment]
        pap._capture_screenshot = Mock()  # type: ignore[method-assign]
        pap._mfa_espera_segundos = 5

        ok, msg = pap._fazer_login_microsoft()

        self.assertTrue(ok)
        self.assertIn("sucesso", msg.lower())
        self.assertEqual(
            [valor for seletor, valor in pagina.fills if "loginfmt" in seletor],
            ["TT398861@vtalcorp.onmicrosoft.com"],
        )
        self.assertEqual(
            [valor for seletor, valor in pagina.fills if "passwd" in seletor],
            ["senha-teste"],
        )
        self.assertLess(
            pagina.fills.index(("input[name=\"loginfmt\"]", "TT398861@vtalcorp.onmicrosoft.com")),
            pagina.fills.index(("input[name=\"passwd\"]", "senha-teste")),
        )

    def test_senha_recusada_nao_reenvia(self) -> None:
        pagina = _PaginaMicrosoft()
        pagina.fase = "senha"
        pagina.texto = "Enter password"
        pagina.email_visivel = False
        pagina.senha_visivel = True

        original_click = pagina.click

        def click(seletor: str, timeout: int = 0) -> None:
            if seletor == "#idSIButton9":
                pagina.clicks.append(seletor)
                pagina.fase = "erro"
                pagina.texto = "Your account or password is incorrect"
                return None
            original_click(seletor, timeout)

        pagina.click = click  # type: ignore[method-assign]
        pap = PAPNioAutomation("TT9", "senha-teste")
        pap.page = pagina  # type: ignore[assignment]
        pap._mfa_espera_segundos = 2

        ok, msg = pap._fazer_login_microsoft()

        self.assertFalse(ok)
        self.assertIn("não bloquear", msg)
        self.assertEqual(
            [valor for seletor, valor in pagina.fills if "passwd" in seletor],
            ["senha-teste"],
        )

    def test_manter_conectado_clica_sim(self) -> None:
        pagina = _PaginaMicrosoft()
        pagina.fase = "kmsi"
        pagina.texto = "Stay signed in"
        pagina.email_visivel = False
        pagina.senha_visivel = False
        pap = PAPNioAutomation("TT9", "senha-teste")
        pap.page = pagina  # type: ignore[assignment]
        pap._mfa_espera_segundos = 3

        ok, _msg = pap._fazer_login_microsoft()

        self.assertTrue(ok)
        self.assertIn("#idSIButton9", pagina.clicks)
        self.assertNotIn("#idBtn_Back", pagina.clicks)
        self.assertEqual(pagina.fills, [])

    def test_continuar_conectado_marca_caixa_e_clica_sim(self) -> None:
        pagina = _PaginaMicrosoft()
        pagina.fase = "kmsi"
        pagina.texto = "Continuar conectado?\nNão mostrar isso novamente"
        pagina.email_visivel = False
        pagina.senha_visivel = False
        caixa = _CaixaNaoMostrar()
        pagina.caixa_nao_mostrar = caixa
        pap = PAPNioAutomation("TT398861", "senha-teste")
        pap.page = pagina  # type: ignore[assignment]
        pap._mfa_espera_segundos = 3

        ok, _msg = pap._fazer_login_microsoft()

        self.assertTrue(ok)
        self.assertTrue(caixa.marcado)
        self.assertEqual(caixa.eventos, ["marcou"])
        self.assertEqual(pagina.clicks, ["#idSIButton9"])
        self.assertNotIn("#idBtn_Back", pagina.clicks)
        self.assertFalse(pagina.avaliou_nao_mostrar)

    def test_continuar_conectado_acha_caixa_pelo_texto(self) -> None:
        pagina = _PaginaMicrosoft()
        pagina.fase = "kmsi"
        pagina.texto = "Continuar conectado?\nNão mostrar isso novamente"
        pagina.email_visivel = False
        pagina.senha_visivel = False
        pap = PAPNioAutomation("TT398861", "senha-teste")
        pap.page = pagina  # type: ignore[assignment]
        pap._mfa_espera_segundos = 3

        ok, _msg = pap._fazer_login_microsoft()

        self.assertTrue(ok)
        self.assertTrue(pagina.avaliou_nao_mostrar)
        self.assertEqual(pagina.clicks, ["#idSIButton9"])
        self.assertNotIn("#idBtn_Back", pagina.clicks)

    def test_redirect_durante_formulario_antigo_segue_na_microsoft(self) -> None:
        pap = PAPNioAutomation("TT713110", "senha-teste")
        pap._aguardar_pagina_estavel = Mock()  # type: ignore[method-assign]
        pap._esperar_tipo_login = Mock(return_value="vtal")  # type: ignore[method-assign]
        pap._deve_login_microsoft = Mock(return_value=False)  # type: ignore[method-assign]
        pap._pagina_senha_expirada = Mock(return_value=False)  # type: ignore[method-assign]
        pap._fazer_login_microsoft = Mock(  # type: ignore[method-assign]
            return_value=(True, "Login realizado com sucesso!")
        )

        class Pagina:
            url = "https://pap.niointernet.com.br/"

            def content(self) -> str:
                return ""

            def wait_for_selector(self, *_args, **_kwargs) -> None:
                raise Exception(
                    'Timeout 10000ms exceeded. navigated to '
                    '"https://login.microsoftonline.com/tenant/saml2"'
                )

            def wait_for_timeout(self, _timeout: int) -> None:
                return None

        pap.page = Pagina()  # type: ignore[assignment]
        ok, msg = pap._fazer_login()

        self.assertTrue(ok)
        self.assertIn("sucesso", msg.lower())
        pap._fazer_login_microsoft.assert_called_once()

    def test_fazer_login_desvia_para_microsoft_sem_repetir(self) -> None:
        pap = PAPNioAutomation("TT9", "senha-teste")
        pap._aguardar_pagina_estavel = Mock()  # type: ignore[method-assign]
        pap._deve_login_microsoft = Mock(return_value=True)  # type: ignore[method-assign]
        pap._fazer_login_microsoft = Mock(return_value=(False, "aguarde o celular"))  # type: ignore[method-assign]

        ok, msg = pap._fazer_login()

        self.assertFalse(ok)
        self.assertEqual(msg, "aguarde o celular")
        pap._fazer_login_microsoft.assert_called_once()


@override_settings(CACHES=_CACHE)
class AvisoBoConectadoTests(SimpleTestCase):
    def tearDown(self) -> None:
        limpar_aviso_mfa()

    def test_mensagem_nao_pede_confirmacao_no_crm(self) -> None:
        texto = mensagem_aviso_mfa("TT123456", "82")
        self.assertIn("TT123456", texto)
        self.assertIn("82", texto)
        self.assertIn("segue sozinho", texto)

    def test_foto_da_tela_fica_disponivel_para_o_modal(self) -> None:
        publicar_tela_login("historico-73", b"foto-jpeg")
        self.assertEqual(
            obter_tela_login_b64("historico-73"),
            "Zm90by1qcGVn",
        )
        limpar_tela_login("historico-73")
        self.assertEqual(obter_tela_login_b64("historico-73"), "")

    def test_so_bo_conectado_ve_o_aviso(self) -> None:
        bo = SimpleNamespace(is_authenticated=True, is_staff=False, is_superuser=False, senha_pap="x")
        vendedor = SimpleNamespace(is_authenticated=True, is_staff=False, is_superuser=False, senha_pap="")
        self.assertTrue(usuario_ve_aviso_mfa(bo))
        self.assertFalse(usuario_ve_aviso_mfa(vendedor))
        self.assertFalse(usuario_ve_aviso_mfa(AnonymousUser()))

        publicar_aviso_mfa("TT123456", "82")
        fabrica = RequestFactory()
        pedido_bo = fabrica.get("/api/crm/pap/mfa-pendente/")
        pedido_bo.user = bo
        corpo = pap_mfa_pendente_view(pedido_bo)
        self.assertEqual(corpo.status_code, 200)
        self.assertIn(b"TT123456", corpo.content)

        pedido_vendedor = fabrica.get("/api/crm/pap/mfa-pendente/")
        pedido_vendedor.user = vendedor
        corpo_vendedor = pap_mfa_pendente_view(pedido_vendedor)
        self.assertIn(b'"pendentes": []', corpo_vendedor.content)
