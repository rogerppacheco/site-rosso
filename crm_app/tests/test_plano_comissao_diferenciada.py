from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from crm_app.comissao_folha_service import (
    _banda_legado_comissao,
    estimar_comissao_instaladas_vendedor,
    plano_tipo_to_chave,
    resolver_valor_comissao_venda,
)
from crm_app.services.comissao_matriz_service import _legacy_valores_faixa_banda


class ComissaoMatrizPlanoTest(SimpleTestCase):
    def test_resolver_usa_matriz_faixa_plano(self) -> None:
        plano = MagicMock()
        plano.id = 99
        faixa = MagicMock()

        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=150.0):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
            )
        self.assertEqual(valor, 150.0)

    def test_resolver_fallback_faixa_legada(self) -> None:
        plano = MagicMock()
        faixa = MagicMock(valor_1gb_pap=Decimal('220.00'))

        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=None):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
            )
        self.assertEqual(valor, 220.0)

    def test_banda_transicao_600_800(self) -> None:
        self.assertEqual(_banda_legado_comissao('600MB'), '500MB')
        self.assertEqual(_banda_legado_comissao('800MB'), '700MB')
        self.assertEqual(_banda_legado_comissao('500MB'), '500MB')

    def test_chave_excel_planos_transicao(self) -> None:
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA ESSENCIAL 600MB', 'CPF'), '600MB_PAP')
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA SUPER 800MB', 'CNPJ'), '700MB_CNPJ')
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA 500MB', 'CPF'), '500MB_PAP')

    def test_chave_600_cidade_especial(self) -> None:
        venda = MagicMock(cidade='CAMPINAS', estado='SP')
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=True,
        ):
            self.assertEqual(
                plano_tipo_to_chave(
                    'NIO FIBRA ESSENCIAL 600MB',
                    'CPF',
                    venda=venda,
                    cidades_especiais_cache={('SP', 'CAMPINAS')},
                ),
                '600MB_ESP_PAP',
            )
        with patch(
            'crm_app.services.comissao_cidade_especial_service.venda_em_cidade_oferta_especial',
            return_value=False,
        ):
            self.assertEqual(
                plano_tipo_to_chave(
                    'NIO FIBRA ESSENCIAL 600MB',
                    'CPF',
                    venda=venda,
                    cidades_especiais_cache=set(),
                ),
                '600MB_PAP',
            )

    def test_chave_legado_lookup_600(self) -> None:
        from crm_app.comissao_folha_service import chave_legado_lookup

        self.assertEqual(chave_legado_lookup('600MB_PAP'), '500MB_PAP')
        self.assertEqual(chave_legado_lookup('600MB_ESP_CNPJ'), '500MB_CNPJ')
        self.assertEqual(chave_legado_lookup('1GB_PAP'), '1GB_PAP')

    def test_legacy_faixa_herda_valores_600_e_800(self) -> None:
        faixa = MagicMock(
            valor_500mb_pap=Decimal('150'),
            valor_500mb_cnpj=Decimal('250'),
            valor_700mb_pap=Decimal('190'),
            valor_700mb_cnpj=Decimal('280'),
            valor_1gb_pap=Decimal('220'),
            valor_1gb_cnpj=Decimal('300'),
        )
        self.assertEqual(
            _legacy_valores_faixa_banda(faixa, '600MB'),
            (Decimal('150'), Decimal('250')),
        )
        self.assertEqual(
            _legacy_valores_faixa_banda(faixa, '800MB'),
            (Decimal('190'), Decimal('280')),
        )

    def test_resolver_cidade_especial_tem_prioridade(self) -> None:
        plano = MagicMock()
        plano.id = 6
        faixa = MagicMock()
        venda = MagicMock(cidade='CAMPINAS', estado='SP')

        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=105.0,
            ),
            patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=180.0),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='500MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 105.0)

    def test_resolver_sem_cidade_especial_usa_matriz(self) -> None:
        plano = MagicMock()
        faixa = MagicMock()
        venda = MagicMock(cidade='SAO PAULO', estado='SP')

        with (
            patch(
                'crm_app.services.comissao_cidade_especial_service.resolver_valor_cidade_especial',
                return_value=None,
            ),
            patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=180.0),
        ):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='500MB_PAP',
                venda=venda,
            )
        self.assertEqual(valor, 180.0)

    def test_estimar_comissao_inclui_plano_sem_regra_legado(self) -> None:
        vendedor = MagicMock(id=1)
        plano_600 = MagicMock(id=6, nome='NIO FIBRA ESSENCIAL 600MB')
        venda = MagicMock(plano=plano_600, plano_id=6, cidade='SAO PAULO', estado='SP')
        faixa = MagicMock(id=10, min_vendas=1, max_vendas=20, perfil='Vendedor')
        ctx = {
            'configs': {},
            'regras_perfil': [faixa],
            'regras_vendedor': {},
        }

        with (
            patch(
                'crm_app.performance_helpers.perfil_comissao_do_consultor',
                return_value='Vendedor',
            ),
            patch(
                'crm_app.services.cnpj_mei_service.tipo_cliente_comissao',
                return_value='CPF',
            ),
            patch(
                'crm_app.services.comissao_cidade_especial_service.carregar_cidades_oferta_especial',
                return_value=set(),
            ),
            patch(
                'crm_app.services.comissao_matriz_service.get_valor_faixa_plano',
                return_value=150.0,
            ),
        ):
            total = estimar_comissao_instaladas_vendedor(
                vendedor,
                [venda],
                ctx_faixas=ctx,
                matriz_cache=None,
            )

        self.assertEqual(total, 150.0)


class ComissaoCidadeEspecialServiceTest(SimpleTestCase):
    def test_cidade_em_oferta_com_cache(self) -> None:
        from crm_app.services.comissao_cidade_especial_service import cidade_em_oferta_especial

        cache = {('SP', 'CAMPINAS'), ('PR', 'LONDRINA')}
        self.assertTrue(cidade_em_oferta_especial('Campinas', 'sp', cache=cache))
        self.assertTrue(cidade_em_oferta_especial('LONDRINA', 'PR', cache=cache))
        self.assertFalse(cidade_em_oferta_especial('São Paulo', 'SP', cache=cache))

    def test_get_valor_so_com_flag_true(self) -> None:
        from crm_app.services.comissao_cidade_especial_service import (
            get_valor_comissao_cidade_especial,
        )

        plano = MagicMock()
        vc = MagicMock()
        vc.usa_comissao_cidade_especial = True
        vc.valor_pap_cidade_especial = Decimal('105.00')
        vc.valor_cnpj_cidade_especial = Decimal('105.00')
        plano.valores_comissao = vc

        self.assertEqual(get_valor_comissao_cidade_especial(plano, 'CPF'), 105.0)

        vc.usa_comissao_cidade_especial = False
        self.assertIsNone(get_valor_comissao_cidade_especial(plano, 'CPF'))

    def test_lista_canonica_tem_161_cidades(self) -> None:
        from crm_app.cidades_oferta_especial_data import CIDADES_OFERTA_ESPECIAL

        self.assertEqual(len(CIDADES_OFERTA_ESPECIAL), 161)
        self.assertIn(('SP', 'CAMPINAS'), CIDADES_OFERTA_ESPECIAL)
        self.assertIn(('PR', 'LONDRINA'), CIDADES_OFERTA_ESPECIAL)
