from datetime import date, time
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from crm_app.models import Comunicado
from crm_app.services.comunicado_service import (
    comunicado_usa_envio_individual,
    processar_envio_comunicado,
    resolver_destinatarios_individuais,
)
from usuarios.models import Perfil

User = get_user_model()


class ComunicadoServiceTestCase(TestCase):
    def setUp(self) -> None:
        self.perfil_vendedor = Perfil.objects.create(
            cod_perfil='vendedor', nome='Vendedor'
        )
        self.vendedor = User.objects.create_user(
            username='vend01',
            password='senha123',
            perfil=self.perfil_vendedor,
            canal='PAP',
            cluster='CLUSTER_1',
            tel_whatsapp='21999990001',
            is_active=True,
        )
        self.comunicado_base = Comunicado.objects.create(
            titulo='Teste',
            mensagem='Linha 1\nLinha 2',
            data_programada=date.today(),
            hora_programada=time(8, 0),
            perfil_destino='TODOS',
        )

    def test_comunicado_vendedor_usa_envio_individual(self) -> None:
        comunicado = Comunicado(perfil_destino='VENDEDOR')
        self.assertTrue(comunicado_usa_envio_individual(comunicado))

    def test_filtro_canal_usa_envio_individual(self) -> None:
        comunicado = Comunicado(perfil_destino='TODOS', canal_alvo='PAP')
        self.assertTrue(comunicado_usa_envio_individual(comunicado))

    def test_resolver_destinatarios_por_canal_e_cluster(self) -> None:
        comunicado = Comunicado(
            perfil_destino='VENDEDOR',
            canal_alvo='PAP',
            cluster_alvo='CLUSTER_1',
            status_destinatarios='somente_ativos',
        )
        destinatarios = resolver_destinatarios_individuais(comunicado)
        self.assertEqual(len(destinatarios), 1)
        self.assertEqual(destinatarios[0].id, self.vendedor.id)

    def test_resolver_vendedor_especifico(self) -> None:
        comunicado = Comunicado(vendedor=self.vendedor)
        destinatarios = resolver_destinatarios_individuais(comunicado)
        self.assertEqual(len(destinatarios), 1)
        self.assertEqual(destinatarios[0].username, 'vend01')

    @patch('crm_app.services.comunicado_service.WhatsAppService')
    def test_envio_preserva_mensagem_sem_variacao(self, mock_service_cls: MagicMock) -> None:
        mock_service = mock_service_cls.return_value
        mock_service.enviar_mensagem_texto.return_value = (True, {'ok': True})

        comunicado = Comunicado.objects.create(
            titulo='Fmt',
            mensagem='Primeira linha\nSegunda linha',
            data_programada=date.today(),
            hora_programada=time(0, 0),
            perfil_destino='VENDEDOR',
            canal_alvo='PAP',
        )

        ok = processar_envio_comunicado(comunicado)
        self.assertTrue(ok)
        mock_service.enviar_mensagem_texto.assert_called_once()
        args, kwargs = mock_service.enviar_mensagem_texto.call_args
        self.assertEqual(args[1], 'Primeira linha\nSegunda linha')
        self.assertFalse(kwargs.get('variar', True))
