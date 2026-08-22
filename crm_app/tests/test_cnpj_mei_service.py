# -*- coding: utf-8 -*-
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from crm_app.models import Cliente, Venda
from crm_app.services.cnpj_mei_service import (
    CLASSIFICACAO_MEI,
    CLASSIFICACAO_NMEI,
    classificar_cnpj_mei,
    elegivel_adiantamento_cnpj,
    elegivel_desconto_boleto_folha,
    extrair_razao_social_brasilapi,
    queryset_clientes_cnpj,
    tipo_cliente_comissao,
    usa_tabela_cnpj_comissao,
    _interpretar_resposta_brasilapi,
)
from unittest.mock import MagicMock


class InterpretarBrasilApiTest(SimpleTestCase):
    def test_mei_pela_opcao(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'natureza_juridica': 'Empresário (Individual)',
                'opcao_pelo_mei': 'Sim',
                'data_exclusao_do_mei': None,
            },
            '12345678000199',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_mei_2135_opcao_false_sem_exclusao(self):
        """BrasilAPI: opcao_pelo_mei=False comum em MEI; não deve virar NMEI."""
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'natureza_juridica': 'Empresário (Individual)',
                'opcao_pelo_mei': False,
                'data_opcao_pelo_mei': None,
                'data_exclusao_do_mei': None,
            },
            '13015154000107',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_mei_2135_micro_exclusao_31_dez(self):
        """Exclusão em 31/12 + micro: fim de exercício, não saída do MEI."""
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'natureza_juridica': 'Empresário (Individual)',
                'opcao_pelo_mei': False,
                'data_opcao_pelo_mei': '2021-09-25',
                'data_exclusao_do_mei': '2025-12-31',
                'porte': 'MICRO EMPRESA',
            },
            '43655857000152',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_mei_opcao_boolean_true(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'opcao_pelo_mei': True,
                'data_exclusao_do_mei': None,
            },
            '66088769000111',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_nmei_pela_natureza(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 3999,
                'natureza_juridica': 'Associação Privada',
                'opcao_pelo_mei': None,
            },
            '19131243000197',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)

    def test_mei_2135_micro_mesmo_com_exclusao_antiga(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'opcao_pelo_mei': False,
                'data_opcao_pelo_mei': '2018-04-02',
                'data_exclusao_do_mei': '2024-12-31',
                'porte': 'MICRO EMPRESA',
            },
            '30082212000126',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_nmei_ltda_micro(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2062,
                'natureza_juridica': 'Sociedade Empresária Limitada',
                'opcao_pelo_mei': False,
                'porte': 'MICRO EMPRESA',
            },
            '08194694000157',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)


class ExtrairRazaoSocialTest(SimpleTestCase):
    def test_razao_social_prioritaria(self):
        nome = extrair_razao_social_brasilapi({
            'razao_social': 'Empresa Teste Ltda',
            'nome_fantasia': 'Fantasia',
        })
        self.assertEqual(nome, 'EMPRESA TESTE LTDA')

    def test_fallback_nome_fantasia(self):
        nome = extrair_razao_social_brasilapi({'nome_fantasia': 'Loja do João'})
        self.assertEqual(nome, 'LOJA DO JOÃO')

    def test_vazio_sem_dados(self):
        self.assertEqual(extrair_razao_social_brasilapi({}), '')
        self.assertEqual(extrair_razao_social_brasilapi(None), '')


class RegrasComissaoMeiTest(SimpleTestCase):
    def _venda(self, doc, mei=None):
        cliente = MagicMock(cpf_cnpj=doc, classificacao_mei=mei)
        venda = MagicMock(cliente=cliente, classificacao_mei=mei)
        return venda

    def test_cpf_usa_pap(self):
        v = self._venda('12345678901')
        self.assertEqual(tipo_cliente_comissao(v), 'CPF')
        self.assertFalse(usa_tabela_cnpj_comissao(v))

    def test_cnpj_mei_usa_pap(self):
        v = self._venda('43655857000152', mei=CLASSIFICACAO_MEI)
        self.assertEqual(tipo_cliente_comissao(v), 'CPF')
        self.assertFalse(usa_tabela_cnpj_comissao(v))
        self.assertFalse(elegivel_adiantamento_cnpj(v))

    def test_cnpj_nmei_usa_cnpj(self):
        v = self._venda('08194694000157', mei=CLASSIFICACAO_NMEI)
        self.assertEqual(tipo_cliente_comissao(v), 'CNPJ')
        self.assertTrue(usa_tabela_cnpj_comissao(v))
        self.assertTrue(elegivel_adiantamento_cnpj(v))


class ElegivelDescontoBoletoFolhaTest(SimpleTestCase):
    def _venda(self, doc: str, mei=None, forma: str = 'BOLETO', adiantada: bool = False):
        cliente = MagicMock(cpf_cnpj=doc, classificacao_mei=mei)
        forma_pagamento = MagicMock(nome=forma)
        venda = MagicMock(
            cliente=cliente,
            classificacao_mei=mei,
            forma_pagamento=forma_pagamento,
            antecipacao_comissao=adiantada,
            adiantamento_sabado_quitado_em=True if adiantada else None,
        )
        return venda

    def test_cpf_boleto_elegivel(self) -> None:
        self.assertTrue(elegivel_desconto_boleto_folha(self._venda('12345678901')))

    def test_cnpj_mei_boleto_elegivel(self) -> None:
        self.assertTrue(elegivel_desconto_boleto_folha(self._venda('43655857000152', mei=CLASSIFICACAO_MEI)))

    def test_cnpj_nmei_boleto_nao_elegivel(self) -> None:
        self.assertFalse(elegivel_desconto_boleto_folha(self._venda('08194694000157', mei=CLASSIFICACAO_NMEI)))

    def test_adiantamento_sabado_quitado_cpf_continua_elegivel(self) -> None:
        self.assertTrue(elegivel_desconto_boleto_folha(self._venda('12345678901', adiantada=True)))

    def test_comissao_antecipada_esteira_nao_elegivel(self) -> None:
        venda = self._venda('12345678901')
        venda.antecipacao_comissao = True
        venda.adiantamento_sabado_quitado_em = None
        self.assertFalse(elegivel_desconto_boleto_folha(venda))

    def test_comissao_antecipada_com_sabado_quitado_elegivel(self) -> None:
        venda = self._venda('12345678901')
        venda.antecipacao_comissao = True
        venda.adiantamento_sabado_quitado_em = True
        self.assertTrue(elegivel_desconto_boleto_folha(venda))

    def test_nao_boleto_nao_elegivel(self) -> None:
        self.assertFalse(elegivel_desconto_boleto_folha(self._venda('12345678901', forma='DÉBITO AUTOMÁTICO')))


class ClassificarCnpjMeiTest(SimpleTestCase):
    @patch('crm_app.services.cnpj_mei_service._consultar_brasilapi')
    def test_nmei_quando_api_falha(self, mock_api):
        mock_api.return_value = None
        r = classificar_cnpj_mei('12345678000199', usar_cache=False)
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)

    def test_cpf_sem_classificacao(self):
        r = classificar_cnpj_mei('12345678901', usar_cache=False)
        self.assertIsNone(r.classificacao)
        self.assertEqual(r.descricao, '-')


class QuerysetClientesCnpjTest(TestCase):
    def test_filtra_cnpj_e_ignora_cpf(self):
        c_cnpj = Cliente.objects.create(
            cpf_cnpj='12345678000199',
            nome_razao_social='EMPRESA TESTE',
        )
        Cliente.objects.create(
            cpf_cnpj='12345678901',
            nome_razao_social='PESSOA CPF',
        )
        ids = list(queryset_clientes_cnpj(apenas_sem_classificacao=True).values_list('id', flat=True))
        self.assertEqual(ids, [c_cnpj.id])

    @patch('crm_app.services.cnpj_mei_service.persistir_classificacao_mei_cliente_e_vendas')
    def test_backfill_atualiza_vendas(self, mock_persistir):
        from crm_app.services.cnpj_mei_service import (
            ResultadoClassificacaoMei,
            backfill_classificacao_mei_lote,
        )

        cliente = Cliente.objects.create(
            cpf_cnpj='19131243000197',
            nome_razao_social='CLIENTE CNPJ',
        )
        venda = Venda.objects.create(cliente=cliente, telefone1='31999999999', telefone2='31988888888')
        mock_persistir.return_value = ResultadoClassificacaoMei(
            classificacao=CLASSIFICACAO_MEI,
            descricao='MEI',
            cache_hit=True,
        )

        r = backfill_classificacao_mei_lote(limite=10)
        self.assertEqual(r['processados_lote'], 1)
        self.assertEqual(r['mei'], 1)
        self.assertEqual(r['vendas_atualizadas'], 1)
        self.assertEqual(r['restantes'], 0)
        self.assertTrue(r['concluido'])
        mock_persistir.assert_called_once()
        self.assertEqual(mock_persistir.call_args[0][0].id, cliente.id)
