from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from crm_app.esteira_pendencia_cliente_service import (
    is_motivo_pendencia_tipo_cliente,
    montar_botoes_pendencia_cliente,
    montar_mensagem_reagendamento_pendencia_cliente,
    tentar_enviar_msg_pendencia_cliente,
    venda_em_status_pendente,
)
from crm_app.models import Cliente, EsteiraVendasConfig, MotivoPendencia, StatusCRM, Venda
from usuarios.models import Perfil, Usuario


class EsteiraPendenciaClienteMsgTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil = Perfil.objects.create(cod_perfil='TPC', nome='Admin')
        cls.user = Usuario.objects.create_user(
            username='user_pend_cli',
            password='SenhaSegura123',
            perfil=cls.perfil,
            first_name='Ana',
            tel_whatsapp='5531987654321',
        )
        cls.cliente = Cliente.objects.create(
            cpf_cnpj='11122233344',
            nome_razao_social='Maria Silva',
        )
        cls.st_cad = StatusCRM.objects.create(nome='CADASTRADA', tipo='Tratamento')
        cls.st_pend = StatusCRM.objects.create(nome='PENDENCIADA', tipo='Esteira', estado='ABERTO')
        cls.motivo_cliente = MotivoPendencia.objects.create(
            nome='0001-AGENDAMENTO OCO',
            tipo_pendencia='CLIENTE',
        )
        cls.motivo_tecnica = MotivoPendencia.objects.create(
            nome='0004-FALHA ETAPAS',
            tipo_pendencia='TÉCNICA',
        )
        EsteiraVendasConfig.objects.create(whatsapp_backoffice='5531987654321')

    def _venda(self, **kwargs):
        defaults = dict(
            vendedor=self.user,
            cliente=self.cliente,
            status_tratamento=self.st_cad,
            status_esteira=self.st_pend,
            motivo_pendencia=self.motivo_cliente,
            ordem_servico='12345678',
            telefone1='21999998888',
            data_agendamento=date(2026, 5, 20),
            periodo_agendamento='MANHA',
            ativo=True,
        )
        defaults.update(kwargs)
        return Venda.objects.create(**defaults)

    def test_is_motivo_tipo_cliente(self):
        self.assertTrue(is_motivo_pendencia_tipo_cliente(self.motivo_cliente))
        self.assertFalse(is_motivo_pendencia_tipo_cliente(self.motivo_tecnica))

    def test_mensagem_contem_whatsapp_nio_e_tom_neutro(self):
        v = self._venda()
        msg = montar_mensagem_reagendamento_pendencia_cliente(v, self.user)
        self.assertIn('Sr(a). Maria', msg)
        self.assertNotIn('Maria Silva', msg)
        self.assertIn('21 3605-1000', msg)
        self.assertIn('especialista de qualidade na Nio Fibra', msg)
        self.assertIn('Na maioria dos casos isso não depende de você', msg)
        self.assertIn('BackOffice', msg)
        self.assertIn('reagendar', msg.lower())

    def test_botao_backoffice_wa_me(self):
        botoes = montar_botoes_pendencia_cliente()
        self.assertEqual(1, len(botoes))
        self.assertEqual('URL', botoes[0]['type'])
        self.assertEqual('Dúvidas (BackOffice)', botoes[0]['label'])
        self.assertIn('wa.me/5531987654321', botoes[0]['url'])

    def test_mensagem_com_botao_sem_numero_parceiro_no_texto(self):
        v = self._venda()
        msg = montar_mensagem_reagendamento_pendencia_cliente(v, self.user, usar_botao_parceiro=True)
        self.assertIn('toque no botão abaixo', msg)
        self.assertNotIn('98765', msg)

    @patch('crm_app.esteira_pendencia_cliente_service._enviar_whatsapp_pendencia_cliente')
    def test_envia_quando_motivo_cliente_e_telefone_ok(self, mock_enviar):
        mock_enviar.return_value = (True, 'msg teste')
        v = self._venda()
        res = tentar_enviar_msg_pendencia_cliente(
            v, self.motivo_cliente, usuario=self.user, enviar_whatsapp=True,
        )
        self.assertTrue(res['enviado'])
        mock_enviar.assert_called_once()
        self.assertTrue(v.msgs_pendencia_cliente_enviadas.filter(sucesso=True).exists())

    def test_nao_envia_motivo_tecnico(self):
        v = self._venda(motivo_pendencia=self.motivo_tecnica)
        res = tentar_enviar_msg_pendencia_cliente(
            v, self.motivo_tecnica, usuario=self.user, enviar_whatsapp=True,
        )
        self.assertFalse(res['enviado'])
        self.assertEqual(0, v.msgs_pendencia_cliente_enviadas.count())

    def test_venda_em_status_pendente(self):
        v = self._venda()
        self.assertTrue(venda_em_status_pendente(v))
