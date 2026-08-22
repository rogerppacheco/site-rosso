from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from crm_app.views import _valor_adiantamento_base_comissao


class _PlanoStub:
    def __init__(self, comissao_base: Decimal | None = None) -> None:
        self.comissao_base = comissao_base


class _VendaStub:
    def __init__(self, plano: _PlanoStub) -> None:
        self.plano = plano
        self.vendedor = Mock()


class ValorAdiantamentoBaseComissaoTests(SimpleTestCase):
    @patch(
        'crm_app.services.cnpj_mei_service.usa_tabela_cnpj_comissao',
        return_value=False,
    )
    @patch(
        'crm_app.comissao_folha_service.carregar_faixa_adiantamento_regras_faixa',
    )
    @patch(
        'crm_app.services.comissao_matriz_service.get_valor_faixa_plano',
        return_value=130.0,
    )
    def test_prioriza_matriz_faixa_plano_para_cpf(
        self,
        get_valor_faixa_plano_mock: Mock,
        carregar_faixa_mock: Mock,
        usa_tabela_cnpj_mock: Mock,
    ) -> None:
        plano = _PlanoStub(comissao_base=Decimal('0.00'))
        venda = _VendaStub(plano)
        faixa = Mock()
        carregar_faixa_mock.return_value = faixa

        valor = _valor_adiantamento_base_comissao(venda)

        self.assertEqual(Decimal('130.0'), valor)
        get_valor_faixa_plano_mock.assert_called_once_with(
            faixa,
            plano,
            'CPF',
        )
        usa_tabela_cnpj_mock.assert_called_once_with(venda)

    @patch(
        'crm_app.services.cnpj_mei_service.usa_tabela_cnpj_comissao',
        return_value=True,
    )
    @patch(
        'crm_app.comissao_folha_service.carregar_faixa_adiantamento_regras_faixa',
        return_value=Mock(),
    )
    @patch(
        'crm_app.services.comissao_matriz_service.get_valor_faixa_plano',
        return_value=None,
    )
    def test_usa_comissao_base_quando_matriz_nao_tem_valor(
        self,
        get_valor_faixa_plano_mock: Mock,
        carregar_faixa_mock: Mock,
        usa_tabela_cnpj_mock: Mock,
    ) -> None:
        plano = _PlanoStub(comissao_base=Decimal('75.00'))
        venda = _VendaStub(plano)

        valor = _valor_adiantamento_base_comissao(venda)

        self.assertEqual(Decimal('75.00'), valor)
        get_valor_faixa_plano_mock.assert_called_once_with(
            carregar_faixa_mock.return_value,
            plano,
            'CNPJ',
        )
        usa_tabela_cnpj_mock.assert_called_once_with(venda)
