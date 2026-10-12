from datetime import date, datetime, timedelta, timezone

from django.test import TestCase
from rest_framework.test import APIClient

from crm_app.models import HistoricoPapBusca, HistoricoPapPedido
from usuarios.models import Usuario

URL = '/api/crm/funil-venda-wpp/historico-pap/pedidos/'


class FunilHistoricoPapPedidosPaginacaoTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.client.force_authenticate(Usuario.objects.create_superuser(username='funil', password='x', email='f@x.com'))
        base = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
        for i in range(60):
            HistoricoPapPedido.objects.create(
                numero_pedido=f'2026{i:06d}',
                tipo_venda='VENDA',
                data_criacao_pap=base + timedelta(days=i % 30, minutes=i),
                payload={
                    'cliente': 'MARIA SILVA' if i == 7 else f'CLIENTE {i}',
                    'cpf': '12345678901' if i == 7 else f'{i:011d}',
                    'chaveStatusPrimario': 'ANALISE_BO' if i % 2 else 'PEDIDO_GERADO',
                },
            )
        for i in range(3):
            HistoricoPapPedido.objects.create(numero_pedido=f'INT{i}', tipo_venda='INTERESSE', payload={})
        self.busca = HistoricoPapBusca.objects.create(
            data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 30),
            novos_numeros=['2026000001', '2026000002'],
        )

    def _get(self, **params):
        resp = self.client.get(URL, {'tipo': 'VENDA', 'busca_id': self.busca.id, **params})
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()

    def test_pagina_sem_limite_de_500_e_contagem_real(self) -> None:
        data = self._get(page=3, page_size=25)
        self.assertEqual(data['count'], 60)
        self.assertEqual(data['total_pages'], 3)
        self.assertEqual(data['page'], 3)
        self.assertEqual(len(data['results']), 10)
        self.assertEqual(data['contagens'], {'VENDA': 60, 'INTERESSE': 3, 'PRE_VENDA': 0})

    def test_pagina_fora_do_intervalo_vai_para_ultima(self) -> None:
        data = self._get(page=99, page_size=50)
        self.assertEqual(data['page'], 2)
        self.assertEqual(len(data['results']), 10)

    def test_ordena_pela_data_do_pedido(self) -> None:
        recentes = self._get(page_size=60)['results']
        antigos = self._get(page_size=60, ordem='antigos')['results']
        self.assertEqual([p['id'] for p in recentes], [p['id'] for p in reversed(antigos)])
        primeiro = HistoricoPapPedido.objects.get(pk=recentes[0]['id'])
        self.assertEqual(
            primeiro.data_criacao_pap,
            HistoricoPapPedido.objects.filter(tipo_venda='VENDA').order_by('-data_criacao_pap').first().data_criacao_pap,
        )

    def test_busca_por_nome_cpf_e_protocolo(self) -> None:
        self.assertEqual([p['protocolo'] for p in self._get(q='maria')['results']], ['2026000007'])
        self.assertEqual(self._get(q='123.456.789-01')['count'], 1)
        self.assertEqual(self._get(q='2026000007')['count'], 1)

    def test_filtros_status_situacao_e_periodo(self) -> None:
        data = self._get(status='ANALISE_BO', page_size=100)
        self.assertEqual(data['count'], 30)
        self.assertEqual(data['contagens']['VENDA'], 30)
        self.assertEqual(data['status_opcoes'], ['ANALISE_BO', 'PEDIDO_GERADO'])

        novos = self._get(situacao='novos')
        self.assertEqual(novos['count'], 2)
        self.assertTrue(all(p['novo_nesta_busca'] for p in novos['results']))
        self.assertEqual(self._get(situacao='base')['count'], 58)

        self.assertEqual(self._get(de='2026-09-01', ate='2026-09-01')['count'], 2)

    def test_meses_disponiveis_pela_data_do_pedido(self) -> None:
        HistoricoPapPedido.objects.create(
            numero_pedido='MARCO1', tipo_venda='VENDA',
            data_criacao_pap=datetime(2026, 3, 31, 20, tzinfo=timezone.utc), payload={},
        )
        meses = self._get()['meses']
        self.assertEqual(meses[0], {'mes': '2026-09', 'total': 60})
        self.assertIn({'mes': '2026-03', 'total': 1}, meses)

    def test_exportar_traz_todos_os_filtrados_sem_paginacao(self) -> None:
        resp = self.client.get(
            URL.replace('pedidos/', 'exportar/'),
            {'tipo': 'VENDA', 'de': '2026-09-01', 'ate': '2026-09-30', 'status': 'ANALISE_BO'},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['linhas'], 30)
        self.assertEqual(data['nome_arquivo'], 'Historico_PAP_VENDA_2026-09-01_a_2026-09-30.xlsx')
        self.assertTrue(data['arquivo_base64'])

    def test_exportar_sem_resultado(self) -> None:
        resp = self.client.get(URL.replace('pedidos/', 'exportar/'), {'tipo': 'VENDA', 'q': 'ninguem-xyz'})
        self.assertEqual(resp.status_code, 404)


class ReescritaUrlVendasPapTests(TestCase):
    def test_troca_pagina_periodo_e_limit(self) -> None:
        from urllib.parse import parse_qs, urlparse

        from crm_app.historico_pap_service import _rewritar_url_vendas_periodo

        url = (
            'https://pap-api.niointernet.com.br/api/portal/vendas?dataInicio=2026-10-01T00:00:00-03:00'
            '&dataFim=2026-10-12T23:59:59-03:00&tipoVenda=VENDA&page=1&limit=15'
        )
        qs = parse_qs(urlparse(_rewritar_url_vendas_periodo(url, date(2026, 3, 1), date(2026, 3, 31), page=4)).query)
        self.assertEqual(qs['page'], ['4'])
        self.assertEqual(qs['limit'], ['200'])
        self.assertTrue(qs['dataInicio'][0].startswith('2026-03-01'))
        self.assertTrue(qs['dataFim'][0].startswith('2026-03-31'))

        sem_page = _rewritar_url_vendas_periodo(url, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(parse_qs(urlparse(sem_page).query)['page'], ['1'])


class JanelasPeriodoPapTests(TestCase):
    def test_divide_mes_em_janelas_contiguas(self) -> None:
        from crm_app.historico_pap_service import _dividir_periodo

        janelas = _dividir_periodo(date(2026, 1, 1), date(2026, 1, 31), 4)
        self.assertEqual(janelas[0][0], date(2026, 1, 1))
        self.assertEqual(janelas[-1][1], date(2026, 1, 31))
        for (_, fim_a), (ini_b, _) in zip(janelas, janelas[1:]):
            self.assertEqual(ini_b, fim_a + timedelta(days=1))
        self.assertLessEqual(len(janelas), 4)

    def test_nao_divide_alem_de_um_dia(self) -> None:
        from crm_app.historico_pap_service import _dividir_periodo

        self.assertEqual(
            _dividir_periodo(date(2026, 1, 1), date(2026, 1, 2), 10),
            [(date(2026, 1, 1), date(2026, 1, 1)), (date(2026, 1, 2), date(2026, 1, 2))],
        )

    def test_pack_de_janela_conta_como_do_periodo(self) -> None:
        from crm_app.historico_pap_service import _chave_pack_vendas, _pack_no_periodo

        url = (
            'https://pap-api.niointernet.com.br/api/portal/vendas?dataInicio=2026-01-09T00%3A00%3A00-03%3A00'
            '&dataFim=2026-01-16T23%3A59%3A59-03%3A00&tipoVenda=VENDA&limit=200&page=2'
        )
        self.assertEqual(_chave_pack_vendas(url), ('2026-01-09', '2026-01-16', 2))
        self.assertTrue(_pack_no_periodo(url, date(2026, 1, 1), date(2026, 1, 31)))
        self.assertFalse(_pack_no_periodo(url, date(2026, 1, 10), date(2026, 1, 31)))


class LimitePapTests(TestCase):
    def test_429_recente_e_lembrado(self) -> None:
        import time

        from crm_app import historico_pap_service as svc

        svc._ULTIMO_429['t'] = 0.0
        self.assertFalse(svc._pap_limitou_recentemente())
        svc._ULTIMO_429['t'] = time.time() - 30
        self.assertTrue(svc._pap_limitou_recentemente())
        self.assertFalse(svc._pap_limitou_recentemente(10))
        svc._ULTIMO_429['t'] = 0.0


class SessaoExpiradaHistoricoPapTests(TestCase):
    def setUp(self) -> None:
        self.login = Usuario.objects.create_user(username='ana', password='x', matricula_pap='TT1', senha_pap='s')
        self.busca = HistoricoPapBusca.objects.create(data_inicio=date(2026, 1, 1), data_fim=date(2026, 1, 31))

    def _rodar(self, loop_side_effect, relogin=(True, 'ok')):
        from unittest import mock

        from crm_app import historico_pap_service as svc

        automacao = mock.MagicMock()
        automacao.iniciar_sessao.return_value = (True, '')
        automacao.garantir_sessao_ativa.return_value = relogin
        with mock.patch.object(svc, '_run_django_sync', side_effect=lambda fn: fn()), \
                mock.patch.object(svc, 'verificar_cooldown_login', return_value=(False, 0)), \
                mock.patch.object(svc, 'limpar_cooldown_login'), \
                mock.patch.object(svc, 'registrar_cooldown_login'), \
                mock.patch('crm_app.services_pap_nio.PAPNioAutomation', return_value=automacao), \
                mock.patch.object(svc, '_executar_loop_busca', side_effect=loop_side_effect) as loop:
            svc._executar_busca(self.busca.id, self.login.id)
        self.busca.refresh_from_db()
        return automacao, loop

    def test_login_microsoft_no_meio_refaz_login_e_recomeca(self) -> None:
        from crm_app.historico_pap_service import PAP_HISTORICO_URL, SessaoPapExpirada

        automacao, loop = self._rodar([SessaoPapExpirada('login.microsoftonline.com'), (True, '')])
        automacao.garantir_sessao_ativa.assert_called_once_with(PAP_HISTORICO_URL)
        self.assertEqual(loop.call_count, 2)
        self.assertNotEqual(self.busca.status, HistoricoPapBusca.STATUS_ERRO)

    def test_relogin_falho_marca_erro_claro(self) -> None:
        from crm_app.historico_pap_service import SessaoPapExpirada

        _, loop = self._rodar([SessaoPapExpirada('x')], relogin=(False, 'senha errada'))
        self.assertEqual(loop.call_count, 1)
        self.assertEqual(self.busca.status, HistoricoPapBusca.STATUS_ERRO)
        self.assertIn('sessão do PAP expirou', self.busca.mensagem)

    def test_pagina_no_idp_levanta_sessao_expirada(self) -> None:
        from unittest import mock

        from crm_app.historico_pap_service import SessaoPapExpirada, _garantir_pagina_no_pap

        with self.assertRaises(SessaoPapExpirada):
            _garantir_pagina_no_pap(mock.Mock(url='https://login.microsoftonline.com/85b/saml2'))
        _garantir_pagina_no_pap(mock.Mock(url='https://pap.niointernet.com.br/administrativo/historico'))
