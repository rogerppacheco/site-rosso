from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from crm_app.comissao_folha_service import _plano_nome_to_banda, plano_tipo_to_chave
from crm_app.models import (
    ComissaoOperadora,
    FormaPagamento,
    Operadora,
    Plano,
    PlanoValoresComissao,
    RegraComissaoFaixa,
    RegraComissaoFaixaPlano,
)
from crm_app.services.gdp_preco_service import calcular_valor_plano_legado
from crm_app.services_sincronizacao import resolver_plano_pap


class BandaPlanoMvnoTest(SimpleTestCase):
    def test_bandas_novas_por_nome(self) -> None:
        self.assertEqual(_plano_nome_to_banda('NIO FIBRA ESSENCIAL 400MB B2B'), '400MB')
        self.assertEqual(_plano_nome_to_banda('NIO FIBRA ULTRA 900MB B2B'), '900MB')
        self.assertEqual(_plano_nome_to_banda('NIO TOTAL 1GB B2B'), '1GB')
        self.assertEqual(_plano_nome_to_banda('NIO ESSENCIAL 700MB'), '700MB')

    def test_velocidade_gdp_quando_nome_sem_velocidade(self) -> None:
        plano = Plano(nome='NIO TOTAL', gdp_velocidade_mbps=1000)
        self.assertEqual(_plano_nome_to_banda(plano), '1GB')

    def test_nome_tem_prioridade_sobre_velocidade_gdp(self) -> None:
        plano = Plano(nome='NIO FIBRA SUPER 700MB', gdp_velocidade_mbps=800)
        self.assertEqual(_plano_nome_to_banda(plano), '700MB')

    def test_chaves_folha_400_e_900_herdam_degrau(self) -> None:
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA ESSENCIAL 400MB B2B', 'CNPJ'), '500MB_CNPJ')
        self.assertEqual(plano_tipo_to_chave('NIO FIBRA ULTRA 900MB B2B', 'CNPJ'), '700MB_CNPJ')
        self.assertEqual(plano_tipo_to_chave(Plano(nome='NIO TOTAL 1GB B2B'), 'CPF'), '1GB_PAP')


class PortfolioMvnoBase(TestCase):
    def setUp(self) -> None:
        self.op = Operadora.objects.create(nome='NIO', usa_pap_nio=True)
        self.outra_op = Operadora.objects.create(nome='VERO')
        self.p600 = Plano.objects.create(nome='NIO FIBRA ESSENCIAL 600MB', valor=Decimal('110'), operadora=self.op)
        self.p800 = Plano.objects.create(nome='NIO FIBRA SUPER 800MB', valor=Decimal('135'), operadora=self.op)
        self.p1g = Plano.objects.create(nome='NIO FIBRA ULTRA 1GB', valor=Decimal('160'), operadora=self.op)
        self.p_vero = Plano.objects.create(nome='VERO 500MB', valor=Decimal('99'), operadora=self.outra_op)
        self.faixa = RegraComissaoFaixa.objects.create(perfil='Vendedor', finalidade='COMISSAO', min_vendas=1, max_vendas=99)
        RegraComissaoFaixaPlano.objects.create(
            faixa=self.faixa, plano=self.p800, valor_pap=Decimal('190'), valor_cnpj=Decimal('280'),
        )
        PlanoValoresComissao.objects.create(
            plano=self.p600,
            usa_comissao_cidade_especial=True,
            valor_pap_cidade_especial=Decimal('105'),
        )
        ComissaoOperadora.objects.create(plano=self.p1g, valor_base=Decimal('300'))

    def _rodar(self, *args) -> str:
        out = StringIO()
        call_command('ativar_portfolio_mvno', *args, stdout=out)
        return out.getvalue()


class ComandoPortfolioMvnoTest(PortfolioMvnoBase):
    def test_simulacao_nao_grava(self) -> None:
        saida = self._rodar('--desativar-antigos')
        self.assertIn('SIMULAÇÃO', saida)
        self.assertFalse(Plano.objects.filter(portfolio='MVNO_2026').exists())
        self.assertTrue(Plano.objects.get(id=self.p800.id).ativo)

    def test_aplicar_cria_planos_e_copia_comissao(self) -> None:
        self._rodar('--aplicar')
        novos = Plano.objects.filter(portfolio='MVNO_2026')
        self.assertEqual(novos.count(), 8)
        self.assertTrue(Plano.objects.get(id=self.p800.id).ativo)

        super_800 = novos.get(nome='NIO SUPER 800MB')
        self.assertEqual(super_800.valor_cartao, Decimal('155.00'))
        self.assertEqual(super_800.qtd_chips_moveis, 1)
        self.assertTrue(super_800.ignorar_preco_gdp)
        celula = RegraComissaoFaixaPlano.objects.get(faixa=self.faixa, plano=super_800)
        self.assertEqual(celula.valor_pap, Decimal('190'))

        fibra_600 = novos.get(nome='NIO FIBRA 600MB')
        self.assertTrue(fibra_600.valores_comissao.usa_comissao_cidade_especial)
        self.assertEqual(novos.get(nome='NIO ULTRA 1GB').comissao_operadora.valor_base, Decimal('300'))
        self.assertEqual(novos.get(nome='NIO TOTAL 1GB B2B').segmento, 'B2B')

    def test_idempotente(self) -> None:
        self._rodar('--aplicar')
        self._rodar('--aplicar')
        self.assertEqual(Plano.objects.filter(portfolio='MVNO_2026').count(), 8)

    def test_desativar_e_reverter(self) -> None:
        self._rodar('--aplicar', '--desativar-antigos', f'--manter-ids={self.p1g.id}')
        self.assertFalse(Plano.objects.get(id=self.p600.id).ativo)
        self.assertFalse(Plano.objects.get(id=self.p800.id).ativo)
        self.assertTrue(Plano.objects.get(id=self.p1g.id).ativo)
        self.assertTrue(Plano.objects.get(id=self.p_vero.id).ativo)

        self._rodar('--reverter', '--aplicar')
        self.assertTrue(Plano.objects.get(id=self.p600.id).ativo)
        self.assertTrue(Plano.objects.get(id=self.p800.id).ativo)
        self.assertEqual(Plano.objects.get(id=self.p600.id).portfolio, '')
        self.assertFalse(Plano.objects.filter(portfolio='MVNO_2026', ativo=True).exists())


class ResolverPapPosTrocaTest(PortfolioMvnoBase):
    def setUp(self) -> None:
        super().setUp()
        self._rodar('--aplicar', '--desativar-antigos')

    def test_fibra_essencial_600_nao_cai_no_essencial_700(self) -> None:
        self.assertEqual(resolver_plano_pap('Nio Fibra Essencial', '600 Mega').nome, 'NIO FIBRA 600MB')

    def test_planos_novos(self) -> None:
        self.assertEqual(resolver_plano_pap('Nio Essencial', '700 Mega').nome, 'NIO ESSENCIAL 700MB')
        self.assertEqual(resolver_plano_pap('Nio Super', '800 Mega').nome, 'NIO SUPER 800MB')
        self.assertEqual(resolver_plano_pap('Nio Ultra', '1 Giga').nome, 'NIO ULTRA 1GB')
        self.assertEqual(resolver_plano_pap('Nio Total', '1 Giga').nome, 'NIO TOTAL 1GB B2B')
        self.assertEqual(resolver_plano_pap('Nio Fibra Ultra', '900 Mega').nome, 'NIO FIBRA ULTRA 900MB B2B')
        self.assertEqual(resolver_plano_pap('Nio Fibra Essencial', '400 Mega').nome, 'NIO FIBRA ESSENCIAL 400MB B2B')


class PrecoCartaoTest(TestCase):
    def test_valor_cartao_do_cadastro(self) -> None:
        op = Operadora.objects.create(nome='NIO')
        plano = Plano.objects.create(
            nome='NIO SUPER 800MB', valor=Decimal('170'), valor_cartao=Decimal('155'), operadora=op,
        )
        cartao = FormaPagamento.objects.create(nome='CARTÃO DE CRÉDITO')
        boleto = FormaPagamento.objects.create(nome='BOLETO')
        self.assertEqual(calcular_valor_plano_legado(plano, cartao), Decimal('155.00'))
        self.assertEqual(calcular_valor_plano_legado(plano, boleto), Decimal('170.00'))


class ListaPlanosApiTest(TestCase):
    def setUp(self) -> None:
        op = Operadora.objects.create(nome='NIO')
        self.ativo = Plano.objects.create(nome='NIO ULTRA 1GB', valor=Decimal('200'), operadora=op)
        self.inativo = Plano.objects.create(nome='NIO FIBRA ULTRA 1GB', valor=Decimal('160'), operadora=op, ativo=False)
        user = get_user_model().objects.create_superuser(username='admin_teste', password='x', email='a@a.com')
        self.client = APIClient()
        self.client.force_authenticate(user)

    def _ids(self, url: str) -> set[int]:
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        return {p['id'] for p in (data if isinstance(data, list) else data['results'])}

    def test_padrao_so_ativos(self) -> None:
        self.assertEqual(self._ids('/api/crm/planos/'), {self.ativo.id})

    def test_incluir_id_traz_plano_inativo_da_venda(self) -> None:
        self.assertEqual(self._ids(f'/api/crm/planos/?incluir_id={self.inativo.id}'), {self.ativo.id, self.inativo.id})

    def test_incluir_inativos(self) -> None:
        self.assertEqual(self._ids('/api/crm/planos/?incluir_inativos=1'), {self.ativo.id, self.inativo.id})
