import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from crm_app.esteira_reagendar_cliente_service import (
    classificar_resposta_inicial,
    deve_tentar_reagendar_cliente,
    enviar_reagendar_cliente,
    gerar_datas_opcao,
    parse_button_id,
    parse_data_resposta,
    parse_turno_resposta,
    processar_resposta_reagendar_cliente,
    resumo_lote,
)
from crm_app.models import Cliente, LembreteInstalacaoEnviado, ReagendamentoClienteSessao, StatusCRM, Venda
from usuarios.models import Perfil, Usuario

TEL = '21987654321'


class ParseRespostasTests(SimpleTestCase):
    def test_botoes_do_template(self):
        self.assertEqual('sim', classificar_resposta_inicial('Sim, pode reagendar'))
        self.assertEqual('nao', classificar_resposta_inicial('Não quero mais'))
        self.assertEqual('atendente', classificar_resposta_inicial('Falar com atendente'))
        self.assertIsNone(classificar_resposta_inicial('qual o valor do plano?'))

    def test_datas_pulam_domingo(self):
        # 2026-10-10 é sábado
        datas = gerar_datas_opcao(a_partir_de=date(2026, 10, 10))
        self.assertEqual([date(2026, 10, 10), date(2026, 10, 12), date(2026, 10, 13)], datas)

    def test_data_por_rotulo_numero_ou_dia_mes(self):
        opcoes = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)]
        self.assertEqual(date(2026, 10, 13), parse_data_resposta('Ter 13/10', opcoes))
        self.assertEqual(date(2026, 10, 14), parse_data_resposta('3', opcoes))
        self.assertEqual(date(2026, 10, 12), parse_data_resposta('pode ser 12/10', opcoes))
        self.assertIsNone(parse_data_resposta('20/10', opcoes))

    def test_turno(self):
        self.assertEqual('MANHA', parse_turno_resposta('Manhã'))
        self.assertEqual('TARDE', parse_turno_resposta('2'))
        self.assertIsNone(parse_turno_resposta('noite'))

    def test_button_ids(self):
        self.assertEqual({'venda_id': 7, 'acao': 'sim'}, parse_button_id('rc_7_sim'))
        self.assertEqual('TARDE', parse_button_id('rc_7_tarde')['turno'])
        self.assertEqual(date(2026, 10, 13), parse_button_id('rc_7_dt_20261013')['data'])
        self.assertIsNone(parse_button_id('pr_7_sim'))


def _svc_ok():
    svc = MagicMock()
    svc.enviar_mensagem_texto.return_value = (True, {})
    svc.enviar_mensagem_com_botoes_reply.return_value = (True, {'messageId': 'btn-1'})
    return svc


class FluxoReagendarClienteTests(TestCase):
    def setUp(self):
        self.svc = _svc_ok()
        patcher = patch('crm_app.esteira_reagendar_cliente_service._svc', return_value=self.svc)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cliente = Cliente.objects.create(cpf_cnpj='12345678901', nome_razao_social='MARIA DA SILVA')
        self.venda = Venda.objects.create(cliente=self.cliente, telefone1=TEL, ativo=True)

    def _enviar(self):
        with patch(
            'crm_app.services.whatsapp.nio_templates.tentar_enviar_ou_texto',
            return_value=(True, {'messages': [{'id': 'wamid.X'}]}, 'template'),
        ) as m:
            r = enviar_reagendar_cliente(self.venda)
        return r, m

    def test_envio_abre_sessao_e_marca_venda(self):
        r, m = self._enviar()
        self.assertTrue(r['ok'])
        params = m.call_args[0][2]
        self.assertEqual('Maria', params[1].title())
        self.venda.refresh_from_db()
        self.assertEqual('ENVIADO', self.venda.cliente_reagendar_status)
        s = ReagendamentoClienteSessao.objects.get(venda=self.venda)
        self.assertEqual('wamid.X', s.whatsapp_message_id)
        self.assertEqual(TEL, s.telefone)

    def test_sim_data_turno_grava_preferencia(self):
        self._enviar()
        tel = '55' + TEL
        self.assertTrue(deve_tentar_reagendar_cliente('Sim, pode reagendar', telefone=tel))
        self.assertTrue(processar_resposta_reagendar_cliente(tel, 'Sim, pode reagendar'))
        s = ReagendamentoClienteSessao.objects.get(venda=self.venda)
        self.assertEqual('DATA', s.etapa)
        primeira = date.fromisoformat(json.loads(s.datas_opcoes_json)[0])

        self.assertTrue(processar_resposta_reagendar_cliente(tel, '1'))
        self.assertTrue(processar_resposta_reagendar_cliente(tel, 'Tarde'))
        self.venda.refresh_from_db()
        self.assertEqual('DEFINIDO', self.venda.cliente_reagendar_status)
        self.assertEqual(primeira, self.venda.cliente_reagendar_data)
        self.assertEqual('TARDE', self.venda.cliente_reagendar_turno)
        s.refresh_from_db()
        self.assertEqual('CONCLUIDO', s.etapa)
        self.assertFalse(deve_tentar_reagendar_cliente('Sim', telefone=tel))

    def test_nao_e_atendente(self):
        self._enviar()
        self.assertTrue(processar_resposta_reagendar_cliente(TEL, 'Não quero mais'))
        self.venda.refresh_from_db()
        self.assertEqual('NAO', self.venda.cliente_reagendar_status)

        self._enviar()
        self.assertTrue(processar_resposta_reagendar_cliente(TEL, 'Falar com atendente'))
        self.venda.refresh_from_db()
        self.assertEqual('ATENDENTE', self.venda.cliente_reagendar_status)
        self.svc.enviar_mensagem_texto.assert_called_with(
            TEL, 'Em breve um especialista irá falar contigo.', variar=False,
        )

    def test_sim_solto_fica_com_lembrete_mais_recente(self):
        self._enviar()
        LembreteInstalacaoEnviado.objects.create(
            telefone=TEL, venda=self.venda,
            data_agendamento=timezone.localdate(), periodo_agendamento='MANHA',
        )
        self.assertFalse(deve_tentar_reagendar_cliente('SIM', telefone=TEL))
        self.assertTrue(deve_tentar_reagendar_cliente('Sim, pode reagendar', telefone=TEL))

    def test_texto_livre_sem_sessao_nao_e_capturado(self):
        self.assertFalse(deve_tentar_reagendar_cliente('Sim', telefone=TEL))

    def test_resumo_lote_nao_reenvia_quem_aguarda(self):
        outra = Venda.objects.create(cliente=self.cliente, telefone1='', ativo=True)
        self._enviar()
        r = resumo_lote(Venda.objects.filter(id__in=[self.venda.id, outra.id]))
        self.assertEqual(2, r['total'])
        self.assertEqual(1, r['aguardando_resposta'])
        self.assertEqual(1, r['sem_telefone'])
        self.assertEqual(0, r['a_enviar'])

        Venda.objects.filter(id=self.venda.id).update(
            cliente_reagendar_enviado_em=timezone.now() - timedelta(hours=80),
        )
        r = resumo_lote(Venda.objects.filter(id__in=[self.venda.id, outra.id]))
        self.assertEqual(1, r['a_enviar'])


class LoteReagendarClienteApiTests(APITestCase):
    URL = '/api/crm/vendas/reagendar-cliente-lote/'

    @classmethod
    def setUpTestData(cls):
        cls.gestor = Usuario.objects.create_user(
            username='gestor_reag_cli', password='SenhaSegura123',
            perfil=Perfil.objects.create(cod_perfil='DIR9', nome='Diretoria'),
        )
        cls.vendedor = Usuario.objects.create_user(
            username='vend_reag_cli', password='SenhaSegura123',
            perfil=Perfil.objects.create(cod_perfil='VND9', nome='Vendedor'),
        )
        cliente = Cliente.objects.create(cpf_cnpj='11122233344', nome_razao_social='JOAO TESTE')
        pend = StatusCRM.objects.create(nome='PENDENCIADA', tipo='Esteira', estado='ABERTO')
        agend = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        for st, tel in ((pend, TEL), (pend, '21911112222'), (agend, '21933334444')):
            Venda.objects.create(vendedor=cls.vendedor, cliente=cliente, status_esteira=st, telefone1=tel, ativo=True)

    def test_vendedor_nao_pode(self):
        self.client.force_authenticate(user=self.vendedor)
        r = self.client.post(self.URL + '?status=PENDEN', {}, format='json')
        self.assertEqual(status.HTTP_403_FORBIDDEN, r.status_code)

    @patch('crm_app.esteira_reagendar_cliente_service.disparar_lote_em_background')
    def test_previa_e_confirmacao_respeitam_aba(self, disparar):
        self.client.force_authenticate(user=self.gestor)
        r = self.client.post(self.URL + '?status=PENDEN&page=2&page_size=50', {}, format='json')
        self.assertEqual(status.HTTP_200_OK, r.status_code)
        self.assertEqual(2, r.json()['a_enviar'])
        disparar.assert_not_called()

        r = self.client.post(self.URL + '?status=PENDEN', {'confirmar': True}, format='json')
        self.assertTrue(r.json()['iniciado'])
        self.assertEqual(2, len(disparar.call_args[0][0]))
