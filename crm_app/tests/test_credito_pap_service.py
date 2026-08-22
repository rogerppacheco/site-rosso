"""Testes das regras de fallback de endereço e contatos da análise de crédito."""

from __future__ import annotations

from typing import Any

from django.test import SimpleTestCase

from crm_app.services.assertiva_localize_service import EnderecoAssertiva
from crm_app.services.credito_pap_service import (
    CODIGO_EMAIL_INVALIDO,
    CODIGO_EMAIL_REJEITADO,
    FORMAS_CARTAO,
    FORMAS_TODAS,
    ORIGEM_ALEATORIO,
    ORIGEM_ASSERTIVA,
    ORIGEM_MISTO,
    ORIGEM_PADRAO,
    ContatoCredito,
    EnderecoCredito,
    SeletorContatosCredito,
    classificar_formas_pagamento,
    consultar_viabilidade_com_fallback,
    extrair_motivo_negativa,
    montar_tentativas_endereco,
    resumo_origem_dados,
)


class RepositorioFake:
    """Guarda as recusas em memória, como o repositório de banco faria."""

    def __init__(self, recusados: set[str] | None = None) -> None:
        self.recusados = {e.lower() for e in (recusados or set())}
        self.registros: list[tuple[str, str]] = []

    def emails_recusados(self, emails: tuple[str, ...]) -> set[str]:
        return {e.lower() for e in emails if e.lower() in self.recusados}

    def registrar_email(self, email: str, motivo: str) -> None:
        self.registros.append((email, motivo))
        self.recusados.add(email.lower())

ENDERECO_PADRAO = EnderecoCredito(
    cep="32140000",
    numero="712",
    referencia="do lado da mecânica",
    logradouro="Avenida Fernão Dias",
    origem=ORIGEM_PADRAO,
)


class AutomacaoFake:
    """Simula as respostas da etapa 2 do PAP para cada endereço consultado."""

    def __init__(self, respostas: dict[str, tuple[bool, str, Any]]) -> None:
        self._respostas = respostas
        self.consultas: list[tuple[str, str]] = []
        self.resets: list[str] = []
        self.reset_ok = True

    def etapa2_viabilidade(self, cep: str, numero: str, referencia: str):
        self.consultas.append((cep, numero))
        return self._respostas[cep]

    def etapa2_preparar_nova_consulta_endereco(self, codigo: str = ""):
        self.resets.append(codigo)
        return self.reset_ok, "ok" if self.reset_ok else "modal travado"

    def etapa2_selecionar_endereco_instalacao(self, indice: int):  # pragma: no cover
        return True, "ok"

    def etapa2_preencher_referencia_e_continuar(self, *args, **kwargs):  # pragma: no cover
        return True, "ok", None

    def etapa2_credito_selecionar_complemento_e_avancar(self, *args, **kwargs):  # pragma: no cover
        return True, "ok", None


class MontarTentativasEnderecoTests(SimpleTestCase):
    def test_endereco_assertiva_vem_antes_do_padrao(self):
        assertiva = EnderecoAssertiva(
            cep="30130001",
            numero="522",
            referencia="Endereço cadastral do cliente",
            logradouro="Avenida Afonso Pena",
        )
        tentativas = montar_tentativas_endereco(
            assertiva, endereco_padrao=ENDERECO_PADRAO
        )
        self.assertEqual(
            [t.origem for t in tentativas], [ORIGEM_ASSERTIVA, ORIGEM_PADRAO]
        )

    def test_sem_assertiva_usa_somente_endereco_padrao(self):
        tentativas = montar_tentativas_endereco(None, endereco_padrao=ENDERECO_PADRAO)
        self.assertEqual(tentativas, (ENDERECO_PADRAO,))

    def test_nao_duplica_quando_assertiva_devolve_endereco_padrao(self):
        assertiva = EnderecoAssertiva(
            cep=ENDERECO_PADRAO.cep,
            numero=ENDERECO_PADRAO.numero,
            referencia="qualquer",
            logradouro=ENDERECO_PADRAO.logradouro,
        )
        tentativas = montar_tentativas_endereco(
            assertiva, endereco_padrao=ENDERECO_PADRAO
        )
        self.assertEqual(len(tentativas), 1)


class ConsultarViabilidadeComFallbackTests(SimpleTestCase):
    def _tentativas(self) -> tuple[EnderecoCredito, ...]:
        return (
            EnderecoCredito(
                cep="30130001",
                numero="522",
                referencia="Endereço cadastral do cliente",
                logradouro="Avenida Afonso Pena",
            ),
            ENDERECO_PADRAO,
        )

    def test_sem_viabilidade_segue_com_endereco_padrao(self):
        automacao = AutomacaoFake(
            {
                "30130001": (False, "❌ Indisponível", "INDISPONIVEL_TECNICO"),
                "32140000": (True, "Etapa 2 concluída! Endereço viável.", None),
            }
        )
        resultado = consultar_viabilidade_com_fallback(automacao, self._tentativas())

        self.assertTrue(resultado.sucesso)
        self.assertTrue(resultado.usou_fallback)
        self.assertEqual(resultado.endereco.origem, ORIGEM_PADRAO)
        self.assertEqual(automacao.resets, ["INDISPONIVEL_TECNICO"])
        self.assertEqual(len(resultado.bloqueios), 1)
        self.assertIn("INDISPONIVEL_TECNICO", resultado.bloqueios[0])

    def test_posse_encontrada_tambem_dispara_fallback(self):
        automacao = AutomacaoFake(
            {
                "30130001": (False, "❌ Posse encontrada", "POSSE_ENCONTRADA"),
                "32140000": (True, "Endereço viável.", None),
            }
        )
        resultado = consultar_viabilidade_com_fallback(automacao, self._tentativas())

        self.assertTrue(resultado.sucesso)
        self.assertEqual(automacao.consultas, [("30130001", "522"), ("32140000", "712")])

    def test_pedido_encontrado_tambem_dispara_fallback(self):
        """Modal 'Pedido encontrado' no endereço deve cair no CEP padrão da loja."""
        automacao = AutomacaoFake(
            {
                "30130001": (False, "❌ Pedido encontrado", "PEDIDO_ENCONTRADO"),
                "32140000": (True, "Endereço viável.", None),
            }
        )
        resultado = consultar_viabilidade_com_fallback(automacao, self._tentativas())

        self.assertTrue(resultado.sucesso)
        self.assertTrue(resultado.usou_fallback)
        self.assertEqual(resultado.endereco.origem, ORIGEM_PADRAO)
        self.assertEqual(automacao.resets, ["PEDIDO_ENCONTRADO"])
        self.assertEqual(automacao.consultas, [("30130001", "522"), ("32140000", "712")])
        self.assertIn("PEDIDO_ENCONTRADO", resultado.bloqueios[0])

    def test_falha_de_portal_nao_tenta_outro_endereco(self):
        automacao = AutomacaoFake(
            {
                "30130001": (False, "Botão Buscar não disponível.", None),
                "32140000": (True, "Endereço viável.", None),
            }
        )
        resultado = consultar_viabilidade_com_fallback(automacao, self._tentativas())

        self.assertFalse(resultado.sucesso)
        self.assertEqual(automacao.consultas, [("30130001", "522")])
        self.assertEqual(automacao.resets, [])

    def test_modal_travado_interrompe_sem_nova_consulta(self):
        automacao = AutomacaoFake(
            {
                "30130001": (False, "❌ Indisponível", "INDISPONIVEL_TECNICO"),
                "32140000": (True, "Endereço viável.", None),
            }
        )
        automacao.reset_ok = False
        resultado = consultar_viabilidade_com_fallback(automacao, self._tentativas())

        self.assertFalse(resultado.sucesso)
        self.assertEqual(automacao.consultas, [("30130001", "522")])

    def test_ambos_sem_viabilidade_retorna_ultimo_erro(self):
        automacao = AutomacaoFake(
            {
                "30130001": (False, "❌ Indisponível cliente", "INDISPONIVEL_TECNICO"),
                "32140000": (False, "❌ Indisponível loja", "INDISPONIVEL_TECNICO"),
            }
        )
        resultado = consultar_viabilidade_com_fallback(automacao, self._tentativas())

        self.assertFalse(resultado.sucesso)
        self.assertEqual(resultado.mensagem, "❌ Indisponível loja")
        self.assertEqual(len(resultado.bloqueios), 2)


class ResultadoModalCreditoTests(SimpleTestCase):
    def test_classifica_todas_as_formas(self):
        self.assertEqual(
            classificar_formas_pagamento("Elegível para todas as formas de pagamento"),
            FORMAS_TODAS,
        )

    def test_classifica_apenas_cartao(self):
        self.assertEqual(
            classificar_formas_pagamento("Elegível apenas para Cartão de Crédito"),
            FORMAS_CARTAO,
        )

    def test_texto_desconhecido_fica_sem_classificacao(self):
        self.assertEqual(classificar_formas_pagamento("Aprovado"), "")
        self.assertEqual(classificar_formas_pagamento(None), "")

    def test_extrai_motivo_do_modal_negado(self):
        modal = (
            "Resultado da análise de crédito\n"
            "Crédito negado\n"
            "CPF/CNPJ com débito na Nio.\n"
            "Consultar outro CPF/CNPJ\n"
            "Salvar interesse"
        )

        self.assertEqual(
            extrair_motivo_negativa(modal), "CPF/CNPJ com débito na Nio."
        )

    def test_motivo_junta_linhas_e_respeita_limite(self):
        modal = "Crédito negado\nSem histórico suficiente.\nTente mais tarde."

        self.assertEqual(
            extrair_motivo_negativa(modal),
            "Sem histórico suficiente. Tente mais tarde.",
        )
        self.assertLessEqual(len(extrair_motivo_negativa("x " * 400)), 300)

    def test_modal_sem_motivo_retorna_vazio(self):
        modal = "Resultado da análise de crédito\nCrédito negado\nOk"

        self.assertEqual(extrair_motivo_negativa(modal), "")
        self.assertEqual(extrair_motivo_negativa(None), "")


class ResumoOrigemDadosTests(SimpleTestCase):
    def _contato(self, origem_telefone: str, origem_email: str) -> ContatoCredito:
        return ContatoCredito(
            telefone="31988887777",
            email="cliente@dominio.com",
            origem_telefone=origem_telefone,
            origem_email=origem_email,
        )

    def test_tudo_do_cliente(self):
        endereco = EnderecoCredito(
            cep="30130001",
            numero="522",
            referencia="Endereço cadastral do cliente",
            origem=ORIGEM_ASSERTIVA,
        )
        resumo = resumo_origem_dados(
            self._contato(ORIGEM_ASSERTIVA, ORIGEM_ASSERTIVA), endereco
        )

        self.assertIn("telefone, e-mail e endereço do cliente", resumo)

    def test_parcial_separa_reais_e_automacao(self):
        resumo = resumo_origem_dados(
            self._contato(ORIGEM_ASSERTIVA, ORIGEM_ALEATORIO), ENDERECO_PADRAO
        )

        self.assertIn("Dados do cliente usados: telefone", resumo)
        self.assertIn("Completado pela automação: e-mail, endereço", resumo)

    def test_sem_dados_do_cliente(self):
        resumo = resumo_origem_dados(
            self._contato(ORIGEM_ALEATORIO, ORIGEM_ALEATORIO), ENDERECO_PADRAO
        )

        self.assertIn("Sem dados do cliente", resumo)

    def test_sem_endereco_resolvido_considera_apenas_contato(self):
        resumo = resumo_origem_dados(
            self._contato(ORIGEM_ASSERTIVA, ORIGEM_ASSERTIVA), None
        )

        self.assertIn("telefone, e-mail e endereço do cliente", resumo)


class SeletorContatosCreditoTests(SimpleTestCase):
    def test_usa_contatos_da_assertiva_primeiro(self):
        seletor = SeletorContatosCredito(
            telefones=("31988887777", "31977776666"),
            emails=("cliente@dominio.com",),
        )
        contato = seletor.atual()

        self.assertEqual(contato.telefone, "31988887777")
        self.assertEqual(contato.telefone_secundario, "31977776666")
        self.assertEqual(contato.email, "cliente@dominio.com")
        self.assertEqual(seletor.origem_contato, ORIGEM_ASSERTIVA)

    def test_telefone_recusado_avanca_e_depois_sorteia(self):
        seletor = SeletorContatosCredito(
            telefones=("31988887777", "31977776666"),
            emails=("cliente@dominio.com",),
        )
        segundo = seletor.proximo_telefone()
        self.assertEqual(segundo.telefone, "31977776666")
        self.assertEqual(segundo.origem_telefone, ORIGEM_ASSERTIVA)

        aleatorio = seletor.proximo_telefone()
        self.assertEqual(aleatorio.origem_telefone, ORIGEM_ALEATORIO)
        self.assertTrue(aleatorio.telefone.startswith("319"))
        self.assertEqual(len(aleatorio.telefone), 11)
        self.assertEqual(aleatorio.email, "cliente@dominio.com")
        self.assertEqual(seletor.origem_contato, ORIGEM_MISTO)

    def test_email_recusado_cai_para_email_validado(self):
        seletor = SeletorContatosCredito(
            telefones=("31988887777",),
            emails=("cliente@dominio.com",),
        )
        contato = seletor.proximo_email()

        self.assertEqual(contato.origem_email, ORIGEM_ALEATORIO)
        self.assertIn("@", contato.email)
        self.assertNotEqual(contato.email, "cliente@dominio.com")
        self.assertEqual(seletor.origem_contato, ORIGEM_MISTO)

    def test_sem_dados_assertiva_usa_tudo_aleatorio(self):
        seletor = SeletorContatosCredito()
        contato = seletor.atual()

        self.assertEqual(contato.origem_telefone, ORIGEM_ALEATORIO)
        self.assertEqual(contato.origem_email, ORIGEM_ALEATORIO)
        self.assertEqual(seletor.origem_contato, ORIGEM_ALEATORIO)

    def test_email_invalido_pula_demais_da_assertiva(self):
        repositorio = RepositorioFake()
        seletor = SeletorContatosCredito(
            telefones=("31988887777",),
            emails=("antigo@live.com", "outro@live.com"),
            repositorio=repositorio,
        )
        contato = seletor.email_recusado(CODIGO_EMAIL_INVALIDO)

        self.assertEqual(contato.origem_email, ORIGEM_ALEATORIO)
        self.assertNotIn(contato.email, ("antigo@live.com", "outro@live.com"))
        self.assertEqual(
            repositorio.registros, [("antigo@live.com", CODIGO_EMAIL_INVALIDO)]
        )

    def test_email_rejeitado_tenta_proximo_da_assertiva(self):
        repositorio = RepositorioFake()
        seletor = SeletorContatosCredito(
            telefones=("31988887777",),
            emails=("primeiro@dominio.com", "segundo@dominio.com"),
            repositorio=repositorio,
        )
        contato = seletor.email_recusado(CODIGO_EMAIL_REJEITADO)

        self.assertEqual(contato.email, "segundo@dominio.com")
        self.assertEqual(contato.origem_email, ORIGEM_ASSERTIVA)
        self.assertEqual(
            repositorio.registros, [("primeiro@dominio.com", CODIGO_EMAIL_REJEITADO)]
        )

    def test_email_ja_recusado_antes_nao_e_tentado(self):
        repositorio = RepositorioFake({"antigo@live.com"})
        seletor = SeletorContatosCredito(
            telefones=("31988887777",),
            emails=("antigo@live.com",),
            repositorio=repositorio,
        )
        contato = seletor.atual()

        self.assertEqual(contato.origem_email, ORIGEM_ALEATORIO)
        self.assertEqual(seletor.emails_descartados, ("antigo@live.com",))
        self.assertEqual(seletor.origem_contato, ORIGEM_MISTO)

    def test_email_aleatorio_recusado_nao_vai_para_o_repositorio(self):
        repositorio = RepositorioFake()
        seletor = SeletorContatosCredito(repositorio=repositorio)
        primeiro = seletor.atual().email
        segundo = seletor.email_recusado(CODIGO_EMAIL_INVALIDO)

        self.assertEqual(repositorio.registros, [])
        self.assertEqual(segundo.origem_email, ORIGEM_ALEATORIO)
        self.assertTrue(primeiro and segundo.email)

    def test_contato_expoe_origens_para_o_historico(self):
        seletor = SeletorContatosCredito(telefones=("31988887777",))
        registro = seletor.atual().como_dict()

        self.assertEqual(registro["telefone"], "31988887777")
        self.assertEqual(registro["origem_telefone"], ORIGEM_ASSERTIVA)
        self.assertEqual(registro["origem_email"], ORIGEM_ALEATORIO)
        self.assertIn("@", str(registro["email"]))

    def test_recusa_de_telefone_aleatorio_gera_novo_numero(self):
        seletor = SeletorContatosCredito()
        gerados = {seletor.atual().telefone}
        for _ in range(4):
            gerados.add(seletor.proximo_telefone().telefone)

        self.assertGreater(len(gerados), 1)
        self.assertTrue(all(len(numero) == 11 for numero in gerados))

    def test_codigos_telefone_recusado_incluem_celular_invalido(self):
        from crm_app.services.credito_pap_service import (
            CODIGO_CELULAR_INVALIDO,
            CODIGO_TELEFONE_REJEITADO,
            CODIGOS_TELEFONE_RECUSADO,
        )

        self.assertIn(CODIGO_TELEFONE_REJEITADO, CODIGOS_TELEFONE_RECUSADO)
        self.assertIn(CODIGO_CELULAR_INVALIDO, CODIGOS_TELEFONE_RECUSADO)

    def test_celular_invalido_da_assertiva_avanca_para_proximo_ou_aleatorio(self):
        """Espelha o loop do fluxo CRÉDITO: CELULAR_INVALIDO não deve abortar."""
        seletor = SeletorContatosCredito(telefones=("31999998888", "31977776666"))
        primeiro = seletor.atual().telefone
        # simula CELULAR_INVALIDO no primeiro → próximo da Assertiva
        segundo = seletor.proximo_telefone()
        self.assertEqual(primeiro, "31999998888")
        self.assertEqual(segundo.telefone, "31977776666")
        self.assertEqual(segundo.origem_telefone, ORIGEM_ASSERTIVA)
        # esgota Assertiva → aleatório
        terceiro = seletor.proximo_telefone()
        self.assertEqual(terceiro.origem_telefone, ORIGEM_ALEATORIO)
        self.assertNotEqual(terceiro.telefone, segundo.telefone)
