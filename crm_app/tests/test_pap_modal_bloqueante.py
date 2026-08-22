from __future__ import annotations

from django.test import SimpleTestCase

from crm_app.services_pap_nio import PAPNioAutomation


class PAPModalBloqueanteTests(SimpleTestCase):
    def test_formatar_linha_endereco(self) -> None:
        linha = PAPNioAutomation._formatar_linha_endereco(
            cep="94.070-320",
            numero="66",
            referencia="Endereço cadastral do cliente",
            logradouro="RUA EXEMPLO",
        )
        self.assertIn("RUA EXEMPLO", linha)
        self.assertIn("CEP 94070320", linha)
        self.assertIn("nº 66", linha)

    def test_mensagem_modal_na_etapa_endereco_inclui_cep(self) -> None:
        pap = PAPNioAutomation("matricula", "senha")
        msg = pap._mensagem_usuario_modal_bloqueante(
            {
                "codigo": "POSSE_ENCONTRADA",
                "titulo": "Posse encontrada",
                "texto": "Já existe pedido em andamento neste endereço.",
            },
            etapa="endereco",
            cep="94070320",
            numero="66",
            referencia="Casa",
        )
        self.assertIn("*Posse encontrada*", msg)
        self.assertIn("Já existe pedido em andamento neste endereço.", msg)
        self.assertIn("📍 *Endereço consultado:*", msg)
        self.assertIn("CEP 94070320", msg)
        self.assertIn("nº 66", msg)

    def test_mensagem_modal_na_etapa_contato_sem_endereco(self) -> None:
        pap = PAPNioAutomation("matricula", "senha")
        msg = pap._mensagem_usuario_modal_bloqueante(
            {
                "codigo": "PEDIDO_ENCONTRADO",
                "titulo": "Pedido encontrado",
                "texto": (
                    "Não é possível abrir um novo pedido, pois já existe "
                    "outro pedido (Nova Fibra) em andamento para este cliente."
                ),
            },
            etapa="contato",
        )
        self.assertIn("*Pedido encontrado*", msg)
        self.assertIn("Nova Fibra", msg)
        self.assertIn("análise de crédito", msg)
        self.assertNotIn("Endereço consultado", msg)
