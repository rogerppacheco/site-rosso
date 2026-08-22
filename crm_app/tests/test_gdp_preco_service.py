"""Testes do serviço de preços GDP (Nio por município)."""
from decimal import Decimal

from django.test import TestCase

from crm_app.models import (
    FormaPagamento,
    GdpPrecoMunicipio,
    LogImportacaoGdpPreco,
    Operadora,
    Plano,
)
from crm_app.services.gdp_preco_service import (
    buscar_preco_gdp,
    calcular_valor_plano_legado,
    normalizar_municipio,
    parse_oferta_string,
    resolver_chave_gdp_plano,
    resolver_valor_plano_params,
)


class GdpPrecoParserTest(TestCase):
    def test_parse_oferta_duplicada_1000(self) -> None:
        oferta = '500 (R$90,00) 600 (R$95,00) 800 (R$120,00) 1000 (R$135,00) 1000 (R$145,00)'
        parsed = parse_oferta_string(oferta)
        self.assertEqual(
            parsed,
            [
                (500, 0, Decimal('90.00')),
                (600, 0, Decimal('95.00')),
                (800, 0, Decimal('120.00')),
                (1000, 0, Decimal('135.00')),
                (1000, 1, Decimal('145.00')),
            ],
        )

    def test_normalizar_municipio(self) -> None:
        self.assertEqual(normalizar_municipio('Maceió'), 'MACEIO')
        self.assertEqual(normalizar_municipio('  Rio Branco '), 'RIO BRANCO')


class GdpPrecoLookupTest(TestCase):
    def setUp(self) -> None:
        self.operadora = Operadora.objects.create(nome='NIO')
        self.plano_500 = Plano.objects.create(
            nome='NIO FIBRA ESSENCIAL 500MB',
            valor=Decimal('100.00'),
            operadora=self.operadora,
            gdp_velocidade_mbps=500,
        )
        self.plano_ultra = Plano.objects.create(
            nome='NIO FIBRA ULTRA 1GB',
            valor=Decimal('160.00'),
            operadora=self.operadora,
            gdp_velocidade_mbps=1000,
            gdp_indice_oferta=1,
        )
        self.forma_cartao = FormaPagamento.objects.create(nome='CARTÃO DE CRÉDITO')
        self.forma_dacc = FormaPagamento.objects.create(nome='DÉBITO AUTOMÁTICO')

        self.log = LogImportacaoGdpPreco.objects.create(
            nome_arquivo='teste.xlsx',
            status='SUCESSO',
            vigente=True,
        )
        GdpPrecoMunicipio.objects.create(
            log_importacao=self.log,
            uf='AL',
            municipio='MACEIO',
            municipio_normalizado='MACEIO',
            cod_ibge='2704302',
            meio_pagamento='CARTAO',
            velocidade_mbps=600,
            indice_oferta=0,
            valor=Decimal('55.00'),
        )
        GdpPrecoMunicipio.objects.create(
            log_importacao=self.log,
            uf='AC',
            municipio='RIO BRANCO',
            municipio_normalizado='RIO BRANCO',
            cod_ibge='1200401',
            meio_pagamento='CARTAO',
            velocidade_mbps=500,
            indice_oferta=0,
            valor=Decimal('90.00'),
        )
        GdpPrecoMunicipio.objects.create(
            log_importacao=self.log,
            uf='AC',
            municipio='RIO BRANCO',
            municipio_normalizado='RIO BRANCO',
            cod_ibge='1200401',
            meio_pagamento='DACC',
            velocidade_mbps=500,
            indice_oferta=0,
            valor=Decimal('100.00'),
        )

    def test_buscar_preco_por_municipio(self) -> None:
        preco = buscar_preco_gdp(
            cidade='Rio Branco',
            uf='AC',
            cod_ibge='1200401',
            plano=self.plano_500,
            meio_pagamento='CARTÃO DE CRÉDITO',
        )
        self.assertEqual(preco, Decimal('90.00'))

    def test_fallback_legado_cartao(self) -> None:
        valor = calcular_valor_plano_legado(self.plano_500, self.forma_cartao)
        self.assertEqual(valor, Decimal('90.00'))

    def test_fallback_legado_cartao_800(self) -> None:
        plano_800 = Plano.objects.create(
            nome='NIO FIBRA SUPER 800MB',
            valor=Decimal('135.00'),
            operadora=self.operadora,
            gdp_velocidade_mbps=800,
        )
        valor = calcular_valor_plano_legado(plano_800, self.forma_cartao)
        self.assertEqual(valor, Decimal('120.00'))

    def test_resolver_chave_plano_ultra(self) -> None:
        self.assertEqual(resolver_chave_gdp_plano(self.plano_ultra), (1000, 1))

    def test_resolver_valor_plano_params_gdp(self) -> None:
        payload = resolver_valor_plano_params(
            plano_id=self.plano_500.id,
            forma_pagamento_id=self.forma_cartao.id,
            cidade='Rio Branco',
            uf='AC',
        )
        self.assertEqual(payload['origem'], 'gdp')
        self.assertEqual(payload['valor'], 90.0)

    def test_montar_texto_script_com_fixo(self) -> None:
        from crm_app.services.gdp_preco_service import montar_texto_script_plano_auditoria

        texto = montar_texto_script_plano_auditoria(
            'NIO FIBRA ULTRA 1GB',
            Decimal('75.00'),
            'BOLETO',
            tem_fixo=True,
        )
        self.assertIn('R$ 75,00', texto)
        self.assertIn('R$ 30,00', texto)
        self.assertIn('R$ 105,00', texto)

    def test_resolver_valor_plano_params_legado(self) -> None:
        payload = resolver_valor_plano_params(
            plano_id=self.plano_500.id,
            forma_pagamento_id=self.forma_dacc.id,
            cidade='Cidade Inexistente',
            uf='SP',
        )
        self.assertEqual(payload['origem'], 'legado')
        self.assertEqual(payload['valor'], 100.0)
