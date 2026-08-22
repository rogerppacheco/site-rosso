# -*- coding: utf-8 -*-
from decimal import Decimal

from django.test import SimpleTestCase

from crm_app.services.adiantamento_sabado_service import (
    calcular_complemento_adiantamento_sabado_folha,
    valor_alvo_adiantamento_sabado_folha,
    valor_pago_adiantamento_sabado_venda,
)


class _PlanoStub:
    def __init__(self, nome: str) -> None:
        self.nome = nome


class _ClienteStub:
    def __init__(self, cpf_cnpj: str = '12345678901') -> None:
        self.cpf_cnpj = cpf_cnpj


class _FaixaStub:
    def __init__(
        self,
        faixa_nome: str = 'Faixa 2',
        valor_500mb_pap: float = 150.0,
        valor_500mb_cnpj: float | None = None,
    ) -> None:
        self.faixa_nome = faixa_nome
        self.valor_500mb_pap = Decimal(str(valor_500mb_pap))
        self.valor_700mb_pap = None
        self.valor_1gb_pap = None
        self.valor_500mb_cnpj = Decimal(str(valor_500mb_cnpj)) if valor_500mb_cnpj is not None else None
        self.valor_700mb_cnpj = None
        self.valor_1gb_cnpj = None


class _ConfigStub:
    def __init__(self, valor_500mb_pap_manual: float = 145.0) -> None:
        self.valor_500mb_pap_manual = Decimal(str(valor_500mb_pap_manual))
        self.valor_700mb_pap_manual = None
        self.valor_1gb_pap_manual = None
        self.valor_500mb_cnpj_manual = None
        self.valor_700mb_cnpj_manual = None
        self.valor_1gb_cnpj_manual = None


class _VendaStub:
    def __init__(self, **kwargs) -> None:
        self.pk = kwargs.pop('pk', 1)
        for chave, valor in kwargs.items():
            setattr(self, chave, valor)


class ValorPagoAdiantamentoSabadoTests(SimpleTestCase):
    def test_prioriza_campo_valor_pago(self) -> None:
        venda = _VendaStub(
            pk=1,
            adiantamento_sabado_valor_pago=Decimal('130.00'),
            adiantamento_sabado_valor=Decimal('180.00'),
        )
        self.assertEqual(130.0, valor_pago_adiantamento_sabado_venda(venda))

    def test_usa_lancamento_quando_campo_vazio(self) -> None:
        venda = _VendaStub(pk=2, adiantamento_sabado_valor=Decimal('180.00'))
        self.assertEqual(
            130.0,
            valor_pago_adiantamento_sabado_venda(venda, {2: 130.0}),
        )


class ValorAlvoAdiantamentoSabadoFolhaTests(SimpleTestCase):
    def test_usa_faixa_comissao_quando_nao_manual(self) -> None:
        venda = _VendaStub(plano=_PlanoStub('500 MB'), cliente=_ClienteStub())
        alvo = valor_alvo_adiantamento_sabado_folha(
            venda,
            faixa_regra=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(150.0, alvo)

    def test_usa_valor_manual_da_config(self) -> None:
        venda = _VendaStub(plano=_PlanoStub('500 MB'), cliente=_ClienteStub())
        alvo = valor_alvo_adiantamento_sabado_folha(
            venda,
            faixa_regra=_FaixaStub(valor_500mb_pap=150.0),
            config=_ConfigStub(valor_500mb_pap_manual=145.0),
            usar_manual=True,
        )
        self.assertEqual(145.0, alvo)


class CalcularComplementoAdiantamentoSabadoFolhaTests(SimpleTestCase):
    def test_complemento_positivo_para_instalada(self) -> None:
        venda = _VendaStub(
            pk=10,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('130.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(20.0, res['total_complemento'])
        self.assertEqual(130.0, res['total_pago'])
        self.assertEqual(150.0, res['total_alvo'])
        self.assertEqual(20.0, res['por_venda'][10]['complemento'])

    def test_complemento_negativo_na_rebaixa(self) -> None:
        venda = _VendaStub(
            pk=11,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('160.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=130.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(-30.0, res['total_complemento'])

    def test_nao_calcula_sem_marcacao(self) -> None:
        venda = _VendaStub(
            pk=12,
            adiantamento_sabado_marcado=False,
            adiantamento_sabado_valor_pago=Decimal('130.00'),
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(0.0, res['total_complemento'])

    def test_complemento_manual_usa_config(self) -> None:
        venda = _VendaStub(
            pk=14,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('100.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=_ConfigStub(valor_500mb_pap_manual=145.0),
            usar_manual=True,
        )
        self.assertEqual(45.0, res['total_complemento'])


class EstornoAdiantamentoSabadoMesTests(SimpleTestCase):
    """Regra de estorno: mês da abertura da O.S. (safra), não data do cancelamento."""

    def _status(self, nome: str) -> object:
        return type('StatusStub', (), {'nome': nome})()

    def _venda_estorno(
        self,
        *,
        status_nome: str,
        data_abertura,
        data_ultima_alteracao=None,
    ) -> _VendaStub:
        return _VendaStub(
            pk=99,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor=Decimal('150.00'),
            adiantamento_sabado_valor_pago=Decimal('150.00'),
            flag_desc_adiantamento_sabado=False,
            status_esteira=self._status(status_nome),
            data_abertura=data_abertura,
            data_ultima_alteracao=data_ultima_alteracao,
        )

    def test_cancelada_abertura_os_no_mes_entra_mesmo_cancelando_depois(self) -> None:
        from datetime import datetime
        from crm_app.services.adiantamento_sabado_service import venda_entra_estorno_adiantamento_sabado_mes

        venda = self._venda_estorno(
            status_nome='CANCELADA',
            data_abertura=datetime(2026, 5, 15),
            data_ultima_alteracao=datetime(2026, 6, 6),
        )
        self.assertTrue(
            venda_entra_estorno_adiantamento_sabado_mes(
                venda, datetime(2026, 5, 1), datetime(2026, 6, 1)
            )
        )

    def test_cancelada_abertura_fora_do_mes_nao_entra(self) -> None:
        from datetime import datetime
        from crm_app.services.adiantamento_sabado_service import venda_entra_estorno_adiantamento_sabado_mes

        venda = self._venda_estorno(
            status_nome='CANCELADA',
            data_abertura=datetime(2026, 6, 2),
            data_ultima_alteracao=datetime(2026, 6, 6),
        )
        self.assertFalse(
            venda_entra_estorno_adiantamento_sabado_mes(
                venda, datetime(2026, 5, 1), datetime(2026, 6, 1)
            )
        )

    def test_sem_data_abertura_nao_entra(self) -> None:
        from datetime import datetime
        from crm_app.services.adiantamento_sabado_service import venda_entra_estorno_adiantamento_sabado_mes

        venda = self._venda_estorno(
            status_nome='CANCELADA',
            data_abertura=None,
            data_ultima_alteracao=datetime(2026, 5, 20),
        )
        self.assertFalse(
            venda_entra_estorno_adiantamento_sabado_mes(
                venda, datetime(2026, 5, 1), datetime(2026, 6, 1)
            )
        )


class ReemissaoAntecipacaoEsteiraTests(SimpleTestCase):
    """Reemissão com antecipação na esteira não deve voltar para QTD A PAGAR."""

    def test_reemissao_com_antecipacao_e_adiantada(self) -> None:
        from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

        venda = _VendaStub(
            reemissao=True,
            antecipacao_comissao=True,
            adiantamento_sabado_marcado=False,
            status_esteira=type('S', (), {'nome': 'INSTALADA'})(),
        )
        self.assertTrue(comissao_ja_adiantada_venda(venda))

    def test_reemissao_sem_antecipacao_nao_e_adiantada(self) -> None:
        from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

        venda = _VendaStub(
            reemissao=True,
            antecipacao_comissao=False,
            adiantamento_sabado_marcado=False,
            status_esteira=type('S', (), {'nome': 'INSTALADA'})(),
        )
        self.assertFalse(comissao_ja_adiantada_venda(venda))


class ComplementoMeiVsCnpjTests(SimpleTestCase):
    def test_mei_usa_tabela_pap_no_complemento(self) -> None:
        venda = _VendaStub(
            pk=20,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('150.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(cpf_cnpj='12345678000199'),
            classificacao_mei='MEI',
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=180.0, faixa_nome='Faixa 2'),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(30.0, res['total_complemento'])
        self.assertEqual('500MB_PAP', res['por_venda'][20]['chave'])
        self.assertEqual('MEI', res['detalhes'][0]['classificacao_mei'])
        self.assertEqual('CPF', res['detalhes'][0]['tipo_cliente'])

    def test_nmei_usa_tabela_cnpj_no_complemento(self) -> None:
        venda = _VendaStub(
            pk=21,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('220.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(cpf_cnpj='12345678000199'),
            classificacao_mei='NMEI',
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_cnpj=250.0, valor_500mb_pap=180.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(30.0, res['total_complemento'])
        self.assertEqual('500MB_CNPJ', res['por_venda'][21]['chave'])
