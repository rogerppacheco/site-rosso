"""Seleção sequencial de TTs pela lista do PAP na análise de crédito."""

from __future__ import annotations

from django.test import TestCase

from crm_app.controle_tts_service import (
    obter_matricula_tt_para_credito_pap,
    obter_proximo_tt_lista_pap,
)
from crm_app.models import ControleTTCreditoCursorPap


class ObtProximoTtListaPapTests(TestCase):
    def test_percorre_lista_em_sequencia_por_bo(self):
        lista = ["TT001", "TT002", "TT003"]

        primeiro = obter_proximo_tt_lista_pap(
            lista, bo_matricula="BO123", matricula_fallback="FALL"
        )
        segundo = obter_proximo_tt_lista_pap(
            lista, bo_matricula="BO123", matricula_fallback="FALL"
        )
        terceiro = obter_proximo_tt_lista_pap(
            lista, bo_matricula="BO123", matricula_fallback="FALL"
        )
        quarto = obter_proximo_tt_lista_pap(
            lista, bo_matricula="BO123", matricula_fallback="FALL"
        )

        self.assertEqual([primeiro, segundo, terceiro, quarto], [
            "TT001",
            "TT002",
            "TT003",
            "TT001",
        ])
        cursor = ControleTTCreditoCursorPap.objects.get(bo_matricula="BO123")
        self.assertEqual(cursor.ultima_matricula, "TT001")
        self.assertEqual(cursor.posicao, 0)

    def test_bos_diferentes_tem_cursores_independentes(self):
        lista = ["TT001", "TT002"]

        a1 = obter_proximo_tt_lista_pap(lista, bo_matricula="BO_A")
        b1 = obter_proximo_tt_lista_pap(lista, bo_matricula="BO_B")
        a2 = obter_proximo_tt_lista_pap(lista, bo_matricula="BO_A")

        self.assertEqual(a1, "TT001")
        self.assertEqual(b1, "TT001")
        self.assertEqual(a2, "TT002")

    def test_pula_matriculas_excluidas_na_mesma_sessao(self):
        lista = ["TT001", "TT002", "TT003"]
        obter_proximo_tt_lista_pap(lista, bo_matricula="BO123")  # avança cursor p/ TT001

        escolhido = obter_proximo_tt_lista_pap(
            lista,
            bo_matricula="BO123",
            excluir={"TT002"},
        )
        self.assertEqual(escolhido, "TT003")

    def test_lista_vazia_usa_fallback(self):
        escolhido = obter_proximo_tt_lista_pap(
            [],
            bo_matricula="BO123",
            matricula_fallback="FALLBACK",
        )
        self.assertEqual(escolhido, "FALLBACK")

    def test_retoma_do_inicio_se_ultima_sumiu_da_lista(self):
        ControleTTCreditoCursorPap.objects.create(
            bo_matricula="BO123",
            ultima_matricula="TT_ANTIGO",
            posicao=99,
        )
        escolhido = obter_proximo_tt_lista_pap(
            ["TT001", "TT002"],
            bo_matricula="BO123",
        )
        self.assertEqual(escolhido, "TT001")


class ObtMatriculaTtParaCreditoPapSequencialTests(TestCase):
    def test_flag_sequencial_usa_cursor_quando_ha_candidatos(self):
        primeiro = obter_matricula_tt_para_credito_pap(
            "FALL",
            candidatos=["TT100", "TT200"],
            bo_matricula="BO99",
            sequencial_pap=True,
        )
        segundo = obter_matricula_tt_para_credito_pap(
            "FALL",
            candidatos=["TT100", "TT200"],
            bo_matricula="BO99",
            sequencial_pap=True,
        )
        self.assertEqual(primeiro, "TT100")
        self.assertEqual(segundo, "TT200")

    def test_sem_flag_sequencial_nao_usa_cursor(self):
        """Modo legado (menor carga) continua disponível sem avançar cursor."""
        escolhido = obter_matricula_tt_para_credito_pap(
            "FALL",
            candidatos=["TT100"],
            bo_matricula="BO99",
            sequencial_pap=False,
        )
        self.assertEqual(escolhido, "TT100")
        self.assertFalse(
            ControleTTCreditoCursorPap.objects.filter(bo_matricula="BO99").exists()
        )
