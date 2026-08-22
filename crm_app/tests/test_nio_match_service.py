"""Match estrito CRM ↔ Nio: só grava par único na mesma data."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from django.test import SimpleTestCase

from crm_app.services.nio_match_service import (
    STATUS_AMBIGUO,
    STATUS_DIVERGENCIA_VALOR,
    STATUS_MATCH,
    STATUS_SEM_MATCH,
    STATUS_SEM_VENCIMENTO,
    decidir_matches,
    fatura_liberada_para_consulta_nio,
    parse_valor,
    valores_divergem,
)


def _fatura(**kwargs: object) -> SimpleNamespace:
    dados = {
        'id': 1,
        'numero_fatura': 1,
        'data_vencimento': date(2026, 6, 30),
        'valor': Decimal('100.00'),
        'codigo_pix': '',
        'codigo_barras': '',
    }
    dados.update(kwargs)
    return SimpleNamespace(**dados)


def _nio(**kwargs: object) -> dict:
    dados = {
        'data_vencimento': date(2026, 6, 30),
        'valor': 100.00,
        'pix': '000201PIXJUNHO',
        'barcode': '34191JUNHO',
        'invoice_id': 'inv-jun',
    }
    dados.update(kwargs)
    return dados


class TestDecidirMatches(SimpleTestCase):
    def test_par_unico_mesma_data_e_match(self) -> None:
        decisoes = decidir_matches(
            [_fatura()],
            [_nio()],
        )
        self.assertEqual(len(decisoes), 1)
        self.assertEqual(decisoes[0]['status'], STATUS_MATCH)
        self.assertTrue(decisoes[0]['salvar'])
        self.assertEqual(decisoes[0]['nio']['codigo_pix'], '000201PIXJUNHO')

    def test_duas_faturas_crm_mesma_data_nao_grava(self) -> None:
        decisoes = decidir_matches(
            [
                _fatura(id=1, numero_fatura=1),
                _fatura(id=2, numero_fatura=2),
            ],
            [_nio(), _nio(invoice_id='inv-2', data_vencimento=date(2026, 7, 30), pix='JUL')],
        )
        statuses = {d['numero_fatura']: d['status'] for d in decisoes}
        self.assertEqual(statuses[1], STATUS_AMBIGUO)
        self.assertFalse(any(d['salvar'] and d['numero_fatura'] == 1 for d in decisoes))
        self.assertFalse(any(d['salvar'] and d['numero_fatura'] == 2 for d in decisoes))

    def test_duas_nio_mesma_data_nao_grava(self) -> None:
        decisoes = decidir_matches(
            [_fatura()],
            [
                _nio(invoice_id='a', pix='AAA'),
                _nio(invoice_id='b', pix='BBB'),
            ],
        )
        self.assertEqual(decisoes[0]['status'], STATUS_AMBIGUO)
        self.assertFalse(decisoes[0]['salvar'])

    def test_datas_diferentes_casam_separado(self) -> None:
        decisoes = decidir_matches(
            [
                _fatura(id=1, numero_fatura=1, data_vencimento=date(2026, 6, 30)),
                _fatura(id=2, numero_fatura=2, data_vencimento=date(2026, 7, 30), valor=Decimal('100')),
            ],
            [
                _nio(invoice_id='jun', data_vencimento=date(2026, 6, 30), pix='PIXJUN'),
                _nio(invoice_id='jul', data_vencimento=date(2026, 7, 30), pix='PIXJUL'),
            ],
        )
        por_num = {d['numero_fatura']: d for d in decisoes}
        self.assertEqual(por_num[1]['status'], STATUS_MATCH)
        self.assertEqual(por_num[2]['status'], STATUS_MATCH)
        self.assertEqual(por_num[1]['nio']['codigo_pix'], 'PIXJUN')
        self.assertEqual(por_num[2]['nio']['codigo_pix'], 'PIXJUL')

    def test_valor_divergente_nao_grava(self) -> None:
        decisoes = decidir_matches(
            [_fatura(valor=Decimal('100.00'))],
            [_nio(valor=150.00)],
        )
        self.assertEqual(decisoes[0]['status'], STATUS_DIVERGENCIA_VALOR)
        self.assertFalse(decisoes[0]['salvar'])

    def test_sem_par_nio(self) -> None:
        decisoes = decidir_matches(
            [_fatura(data_vencimento=date(2026, 6, 30))],
            [_nio(data_vencimento=date(2026, 8, 30), invoice_id='ago')],
        )
        self.assertEqual(decisoes[0]['status'], STATUS_SEM_MATCH)
        self.assertFalse(decisoes[0]['salvar'])

    def test_sem_vencimento(self) -> None:
        decisoes = decidir_matches([_fatura(data_vencimento=None)], [_nio()])
        self.assertEqual(decisoes[0]['status'], STATUS_SEM_VENCIMENTO)
        self.assertFalse(decisoes[0]['salvar'])

    def test_crm_sem_valor_nao_e_divergencia(self) -> None:
        decisoes = decidir_matches(
            [_fatura(valor=Decimal('0'))],
            [_nio(valor=100.00)],
        )
        self.assertEqual(decisoes[0]['status'], STATUS_MATCH)
        self.assertTrue(decisoes[0]['salvar'])


class TestParseValor(SimpleTestCase):
    def test_br_e_decimal(self) -> None:
        self.assertEqual(parse_valor('100,00'), Decimal('100.00'))
        self.assertEqual(parse_valor(100), Decimal('100.00'))
        self.assertTrue(valores_divergem(Decimal('100'), 150))
        self.assertFalse(valores_divergem(Decimal('100.00'), 100.02))


class TestFaturaLiberadaConsulta(SimpleTestCase):
    def test_fatura_futura_nao_consulta(self) -> None:
        fatura = _fatura(
            numero_fatura=8,
            data_vencimento=date(2027, 2, 28),
            data_disponibilidade=date(2027, 2, 25),
        )
        self.assertFalse(
            fatura_liberada_para_consulta_nio(fatura, hoje=date(2026, 8, 18))
        )

    def test_fatura_do_mes_corrente_consulta(self) -> None:
        fatura = _fatura(
            numero_fatura=3,
            data_vencimento=date(2026, 8, 30),
            data_disponibilidade=date(2026, 8, 27),
        )
        self.assertTrue(
            fatura_liberada_para_consulta_nio(fatura, hoje=date(2026, 8, 28))
        )
        self.assertFalse(
            fatura_liberada_para_consulta_nio(fatura, hoje=date(2026, 8, 18))
        )

    def test_fatura1_disponivel_apos_instalacao(self) -> None:
        fatura = _fatura(
            numero_fatura=1,
            data_disponibilidade=date(2026, 6, 4),
        )
        self.assertTrue(
            fatura_liberada_para_consulta_nio(fatura, hoje=date(2026, 8, 18))
        )

    def test_fora_da_faixa_1_a_10(self) -> None:
        fatura = _fatura(numero_fatura=11, data_disponibilidade=date(2026, 1, 1))
        self.assertFalse(
            fatura_liberada_para_consulta_nio(fatura, hoje=date(2026, 8, 18))
        )
