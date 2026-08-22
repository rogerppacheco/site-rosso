"""Testes do envio da máscara Sem SLOT (WhatsApp + e-mail do GC)."""
from datetime import date
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from crm_app.auditoria_sem_slot_utils import processar_envio_sem_slot
from crm_app.models import AnteciparInstalacaoConfig, Cliente, Venda
from usuarios.models import Usuario

PNG_1X1 = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


class EnvioSemSlotEmailGcTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(username='aud_slot', password='x', first_name='Auditor')
        cls.vendedor = Usuario.objects.create_user(username='vend_slot', password='x', first_name='Vendedor')
        cls.cliente = Cliente.objects.create(nome_razao_social='Cliente Slot', cpf_cnpj='12345678901')
        cls.venda = Venda.objects.create(
            vendedor=cls.vendedor,
            cliente=cls.cliente,
            ordem_servico='OS999001',
            ativo=True,
        )
        cls.config = AnteciparInstalacaoConfig.objects.create(
            nome_gc='Marcella Silva',
            telefone_gc='21999998888',
            email_gc='gc@exemplo.com',
            telefones_destino=[],
            sem_slot_email_gc_ativo=True,
        )

    def _print_pap(self) -> SimpleUploadedFile:
        return SimpleUploadedFile('print_pap.png', PNG_1X1, content_type='image/png')

    def _enviar(self):
        return processar_envio_sem_slot(
            usuario=self.usuario,
            venda=self.venda,
            ordem_servico='OS999001',
            uf='RJ',
            endereco='Rua Teste, 10, Centro, Rio de Janeiro - RJ, 20000000',
            data_agendamento_cadastrada=date(2026, 8, 14),
            turno_agendamento_cadastrado='MANHA',
            data_desejada_cliente=date(2026, 8, 15),
            turno_desejado_cliente='TARDE',
            telefone_contato='21988887777',
            imagem_upload=self._print_pap(),
        )

    @patch('crm_app.services.teams_notification_service.enviar_teams_operacional', return_value=(False, ''))
    @patch('crm_app.services.pedido_ajuda_gc_service.enviar_email_gc')
    @patch('crm_app.auditoria_sem_slot_utils.WhatsAppService')
    def test_envia_mascara_por_email_quando_gc_configurado(self, mock_wpp, mock_email, _mock_teams):
        mock_email.return_value = (True, '')
        registro, sucesso, msg = self._enviar()
        self.assertTrue(sucesso)
        self.assertTrue(registro.enviado_email)
        mock_wpp.assert_not_called()
        mock_email.assert_called_once()
        args, kwargs = mock_email.call_args
        self.assertEqual(args[0], 'gc@exemplo.com')
        self.assertIn('Sem SLOT', kwargs['assunto'])
        self.assertIn('OS999001', kwargs['assunto'])
        self.assertIn('Pedido: OS999001', kwargs['corpo_texto'])
        self.assertIn('e-mail do GC', msg)

    @patch('crm_app.services.teams_notification_service.enviar_teams_operacional', return_value=(False, ''))
    @patch('crm_app.services.pedido_ajuda_gc_service.enviar_email_gc')
    @patch('crm_app.auditoria_sem_slot_utils.WhatsAppService')
    def test_nao_envia_email_quando_toggle_desligado(self, mock_wpp, mock_email, _mock_teams):
        self.config.sem_slot_email_gc_ativo = False
        self.config.telefones_destino = ['21999998888']
        self.config.save(update_fields=['sem_slot_email_gc_ativo', 'telefones_destino'])
        mock_wpp.return_value.enviar_imagem_b64.return_value = True
        registro, sucesso, _msg = self._enviar()
        self.assertTrue(sucesso)
        self.assertFalse(registro.enviado_email)
        mock_email.assert_not_called()

    def test_falha_sem_destino_whatsapp_nem_email(self):
        self.config.email_gc = ''
        self.config.sem_slot_email_gc_ativo = True
        self.config.telefones_destino = []
        self.config.save(update_fields=['email_gc', 'sem_slot_email_gc_ativo', 'telefones_destino'])
        registro, sucesso, msg = self._enviar()
        self.assertIsNone(registro)
        self.assertFalse(sucesso)
        self.assertIn('e-mail do GC', msg)
