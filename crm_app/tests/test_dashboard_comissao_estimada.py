from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from crm_app.comissao_folha_service import (
    encontrar_faixa_comissao,
    estimar_comissao_instaladas,
)


class _FaixaStub:
    def __init__(self, perfil=None, vendedor_id=None, min_v=0, max_v=99999):
        self.perfil = perfil
        self.vendedor_id = vendedor_id
        self.min_vendas = min_v
        self.max_vendas = max_v


class _ConsultorStub:
    def __init__(self, pk: int, perfil_nome: str = 'Vendedor') -> None:
        self.id = pk
        self.perfil = MagicMock(nome=perfil_nome)


class EncontrarFaixaComissaoTest(SimpleTestCase):
    def test_prioriza_regra_individual_do_vendedor(self) -> None:
        consultor = _ConsultorStub(10)
        faixa_individual = _FaixaStub(vendedor_id=10, min_v=0, max_v=99)
        faixa_perfil = _FaixaStub(perfil='Vendedor', min_v=0, max_v=99)

        encontrada = encontrar_faixa_comissao(
            consultor,
            5,
            [faixa_perfil],
            {10: [faixa_individual]},
        )
        self.assertIs(encontrada, faixa_individual)

    def test_usa_faixa_do_perfil_quando_nao_ha_individual(self) -> None:
        consultor = _ConsultorStub(10, perfil_nome='Supervisor')
        faixa_vendedor = _FaixaStub(perfil='Vendedor', min_v=0, max_v=10)
        faixa_supervisor = _FaixaStub(perfil='Supervisor', min_v=0, max_v=10)

        encontrada = encontrar_faixa_comissao(
            consultor,
            3,
            [faixa_vendedor, faixa_supervisor],
            {},
        )
        self.assertIs(encontrada, faixa_supervisor)

    def test_cai_para_perfil_se_individual_nao_cobre_quantidade(self) -> None:
        consultor = _ConsultorStub(10)
        faixa_individual = _FaixaStub(vendedor_id=10, min_v=0, max_v=2)
        faixa_perfil = _FaixaStub(perfil='Vendedor', min_v=3, max_v=99)

        encontrada = encontrar_faixa_comissao(
            consultor,
            5,
            [faixa_perfil],
            {10: [faixa_individual]},
        )
        self.assertIs(encontrada, faixa_perfil)


class EstimarComissaoInstaladasTest(SimpleTestCase):
    def test_soma_valores_configurados_das_instaladas(self) -> None:
        consultor = _ConsultorStub(7)
        plano = MagicMock()
        plano.nome = '700MB'
        vendas = [MagicMock(plano=plano), MagicMock(plano=plano)]
        faixa = _FaixaStub(perfil='Vendedor', min_v=0, max_v=99)
        contexto = {
            'regras_perfil': [faixa],
            'regras_vendedor': {},
            'configs': {},
            'matriz_cache': object(),
        }

        with patch(
            'crm_app.services.cnpj_mei_service.tipo_cliente_comissao',
            return_value='CPF',
        ), patch(
            'crm_app.comissao_folha_service.resolver_valor_comissao_venda',
            return_value=130.0,
        ) as resolver_mock:
            total = estimar_comissao_instaladas(consultor, vendas, contexto)

        self.assertEqual(total, 260.0)
        self.assertEqual(resolver_mock.call_count, 2)

    def test_retorna_zero_sem_instaladas(self) -> None:
        consultor = _ConsultorStub(7)
        self.assertEqual(estimar_comissao_instaladas(consultor, [], {'configs': {}}), 0.0)
