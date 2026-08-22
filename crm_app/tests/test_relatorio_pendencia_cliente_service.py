"""Testes do relatório de pendências CLIENTE por vendedor (Esteira → WhatsApp)."""
from datetime import datetime, time
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from crm_app.models import Cliente, EsteiraVendasConfig, GrupoDisparo, MotivoPendencia, StatusCRM, Venda
from crm_app.services.relatorio_pendencia_cliente_service import (
    contar_pendencias_cliente_por_vendedor,
    montar_caption_pendencia_cliente,
    processar_envio_relatorio_pendencia_cliente,
)
from usuarios.models import Usuario


class RelatorioPendenciaClienteServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.st_pend = StatusCRM.objects.create(nome='PENDENTE', tipo='Esteira', estado='ABERTO')
        cls.st_agend = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        cls.motivo_cli = MotivoPendencia.objects.create(nome='Doc pendente', tipo_pendencia='Cliente')
        cls.motivo_tec = MotivoPendencia.objects.create(nome='Rede', tipo_pendencia='Técnica')
        cls.vend_b = Usuario.objects.create_user(username='bruno', password='x', first_name='Bruno')
        cls.vend_a = Usuario.objects.create_user(username='ana', password='x', first_name='Ana')
        cls.cliente = Cliente.objects.create(nome_razao_social='Cli Teste', cpf_cnpj='12345678901')
        cls.grupo = GrupoDisparo.objects.create(
            nome='Comercial',
            chat_id='120363000000000000@g.us',
            ativo=True,
        )
        cls.config = EsteiraVendasConfig.objects.create(
            whatsapp_backoffice='',
            relatorio_pendencia_cliente_ativo=True,
            relatorio_pendencia_cliente_horario_1=time(12, 0),
            relatorio_pendencia_cliente_horario_2=time(18, 0),
        )
        cls.config.relatorio_pendencia_cliente_grupos.add(cls.grupo)

    def _criar_venda(self, *, vendedor, motivo, status):
        return Venda.objects.create(
            vendedor=vendedor,
            cliente=self.cliente,
            ativo=True,
            motivo_pendencia=motivo,
            status_esteira=status,
        )

    def test_conta_apenas_pendencia_cliente_e_ordena_alfabetico(self):
        self._criar_venda(vendedor=self.vend_b, motivo=self.motivo_cli, status=self.st_pend)
        self._criar_venda(vendedor=self.vend_b, motivo=self.motivo_cli, status=self.st_pend)
        self._criar_venda(vendedor=self.vend_a, motivo=self.motivo_cli, status=self.st_pend)
        # Fora do escopo: técnica e agendado
        self._criar_venda(vendedor=self.vend_a, motivo=self.motivo_tec, status=self.st_pend)
        self._criar_venda(vendedor=self.vend_a, motivo=self.motivo_cli, status=self.st_agend)

        metricas = contar_pendencias_cliente_por_vendedor()
        self.assertEqual(metricas['total'], 3)
        self.assertEqual([i['nome'] for i in metricas['lista']], ['Ana', 'Bruno'])
        self.assertEqual(metricas['lista'][0]['qtd'], 1)
        self.assertEqual(metricas['lista'][1]['qtd'], 2)

    def test_caption_lista_alfabetica(self):
        metricas = {
            'total': 3,
            'lista': [{'nome': 'Ana', 'qtd': 1}, {'nome': 'Bruno', 'qtd': 2}],
        }
        msg = montar_caption_pendencia_cliente(metricas, slot='12:00', agora=datetime(2026, 8, 12, 12, 0))
        self.assertIn('Pendências CLIENTE', msg)
        self.assertIn('Total: 3', msg)
        self.assertIn('Ana — 1', msg)
        self.assertIn('Bruno — 2', msg)
        self.assertLess(msg.index('Ana'), msg.index('Bruno'))

    @patch('crm_app.services.relatorio_pendencia_cliente_service.WhatsAppService')
    @patch('crm_app.services.relatorio_pendencia_cliente_service.gerar_imagem_pendencia_cliente_b64')
    def test_processar_envio_no_horario(self, mock_img, mock_svc_cls):
        mock_img.return_value = 'data:image/png;base64,abc'
        mock_svc = MagicMock()
        mock_svc.enviar_imagem_b64.return_value = {'messageId': '1'}
        mock_svc_cls.return_value = mock_svc

        self._criar_venda(vendedor=self.vend_a, motivo=self.motivo_cli, status=self.st_pend)
        # Quarta-feira 12:02
        agora = timezone.make_aware(datetime(2026, 8, 12, 12, 2))
        with patch(
            'crm_app.services.relatorio_pendencia_cliente_service.timezone.localtime',
            return_value=agora,
        ):
            processar_envio_relatorio_pendencia_cliente()

        mock_svc.enviar_imagem_b64.assert_called_once()
        self.config.refresh_from_db()
        self.assertEqual(
            self.config.relatorio_pendencia_cliente_controle_disparos.get('slots'),
            ['12:00'],
        )

    def test_nao_envia_se_inativo(self):
        self.config.relatorio_pendencia_cliente_ativo = False
        self.config.save(update_fields=['relatorio_pendencia_cliente_ativo'])
        agora = timezone.make_aware(datetime(2026, 8, 12, 12, 2))
        with patch('crm_app.services.relatorio_pendencia_cliente_service.WhatsAppService') as mock_svc_cls:
            with patch(
                'crm_app.services.relatorio_pendencia_cliente_service.timezone.localtime',
                return_value=agora,
            ):
                processar_envio_relatorio_pendencia_cliente()
            mock_svc_cls.assert_not_called()
