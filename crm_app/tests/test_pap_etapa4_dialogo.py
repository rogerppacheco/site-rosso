"""Dialog do PAP não pode interceptar o Avançar da etapa 4."""

from __future__ import annotations

from django.test import SimpleTestCase

from crm_app.services_pap_nio import PAPNioAutomation


class _AlvoAvançar:
    def __init__(self, pagina: "PaginaEtapa4") -> None:
        self.pagina = pagina

    def click(self, timeout: int | None = None, force: bool = False) -> None:
        if self.pagina.dialogo:
            raise TimeoutError(
                "ElementHandle.click: Timeout 25000ms exceeded. "
                '<div role="dialog" aria-modal="true" '
                'aria-labelledby="contained-modal-title-vcenter" class="modal show"> '
                "intercepts pointer events"
            )
        self.pagina.cliques.append("Avançar")


class PaginaEtapa4:
    def __init__(self, dialogo: dict | None) -> None:
        self.dialogo = dialogo
        self.cliques: list[str] = []
        self.alvo = _AlvoAvançar(self)

    def evaluate(self, script: str, arg: str | None = None):
        if "etapa4-ler-dialogo" in script:
            return self.dialogo
        if "etapa4-clicar-dialogo" in script:
            if not self.dialogo or not arg:
                return False
            botoes = [str(b) for b in (self.dialogo.get("botoes") or [])]
            if arg not in botoes:
                return False
            self.cliques.append(arg)
            self.dialogo = None
            return True
        raise AssertionError(f"script inesperado: {script[:80]}")

    def query_selector(self, selector: str):
        if "Avançar" in selector:
            return self.alvo
        return None

    def wait_for_timeout(self, timeout: int) -> None:
        self.ultima_espera = timeout


class Etapa4DialogoInterceptaCliqueTests(SimpleTestCase):
    def test_dialogo_e_dispensado_e_avancar_segue(self) -> None:
        pagina = PaginaEtapa4(
            {
                "titulo": "Atenção!",
                "texto": "Atenção!\nConfirme os dados de contato para seguir.\nOk",
                "botoes": ["Ok"],
            }
        )
        pap = PAPNioAutomation("matricula", "senha")
        pap.page = pagina  # type: ignore[assignment]

        clicou, erro = pap._etapa4_clicar_avancar_contato()

        self.assertTrue(clicou)
        self.assertIsNone(erro)
        self.assertEqual(pagina.cliques, ["Ok", "Avançar"])
        self.assertIsNone(pagina.dialogo)

    def test_sessao_expirada_fecha_antes_do_avancar(self) -> None:
        pagina = PaginaEtapa4(
            {
                "titulo": "Sessão expirada",
                "texto": "Sessão expirada. Feche seu navegador e logar novamente no portal.\nFechar",
                "botoes": ["Fechar"],
            }
        )
        pap = PAPNioAutomation("matricula", "senha")
        pap.page = pagina  # type: ignore[assignment]

        clicou, erro = pap._etapa4_clicar_avancar_contato()

        self.assertTrue(clicou)
        self.assertIsNone(erro)
        self.assertEqual(pagina.cliques, ["Fechar", "Avançar"])

    def test_rejeicao_de_contato_nao_clica_avancar(self) -> None:
        pagina = PaginaEtapa4(
            {
                "titulo": "Atenção!",
                "texto": "Atenção!\nO celular já utilizado em outro pedido.\nOk",
                "botoes": ["Ok"],
            }
        )
        pap = PAPNioAutomation("matricula", "senha")
        pap.page = pagina  # type: ignore[assignment]

        clicou, erro = pap._etapa4_clicar_avancar_contato()

        self.assertFalse(clicou)
        self.assertEqual(erro, "TELEFONE_REJEITADO")
        self.assertEqual(pagina.cliques, ["Ok"])
        self.assertNotIn("Avançar", pagina.cliques)
