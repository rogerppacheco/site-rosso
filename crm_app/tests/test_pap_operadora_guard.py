"""Bloqueio do PAP Nio conforme o cadastro da operadora."""
from django.test import TestCase

from crm_app.models import Cliente, Operadora, Plano, StatusCRM, Venda
from crm_app.services.pap_operadora_guard import (
    bloqueio_por_documento,
    filtro_vendas_com_pap,
    pap_nio_habilitado,
    venda_liberada_para_pap,
)
from usuarios.models import Usuario


class PapOperadoraGuardTest(TestCase):
    def setUp(self) -> None:
        self.nio = Operadora.objects.create(nome='NIO', usa_pap_nio=True)
        self.vero = Operadora.objects.create(nome='Vero', usa_pap_nio=False)
        self.plano_nio = Plano.objects.create(nome='NIO 600', valor=100, operadora=self.nio)
        self.plano_vero = Plano.objects.create(nome='VERO 700', valor=120, operadora=self.vero)
        self.usuario = Usuario.objects.create_user(username='papguard', password='teste')
        self.status = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        self.cliente_nio = Cliente.objects.create(
            nome_razao_social='Cliente Nio',
            cpf_cnpj='52998224725',
        )
        self.cliente_vero = Cliente.objects.create(
            nome_razao_social='Cliente Vero',
            cpf_cnpj='11144477735',
        )
        self.venda_nio = Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente_nio,
            plano=self.plano_nio,
            status_esteira=self.status,
            ordem_servico='OSNIO1',
        )
        self.venda_vero = Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente_vero,
            plano=self.plano_vero,
            status_esteira=self.status,
            ordem_servico='OSVERO1',
        )

    def test_nova_operadora_nasce_sem_pap(self) -> None:
        velox = Operadora.objects.create(nome='Velox')
        self.assertFalse(velox.usa_pap_nio)

    def test_pap_habilitado_somente_quando_nio_marcada(self) -> None:
        self.assertTrue(pap_nio_habilitado())
        self.nio.usa_pap_nio = False
        self.nio.save(update_fields=['usa_pap_nio'])
        self.assertFalse(pap_nio_habilitado())

    def test_venda_nio_liberada_e_vero_bloqueada(self) -> None:
        ok_nio, msg_nio = venda_liberada_para_pap(self.venda_nio)
        ok_vero, msg_vero = venda_liberada_para_pap(self.venda_vero)
        self.assertTrue(ok_nio)
        self.assertEqual(msg_nio, '')
        self.assertFalse(ok_vero)
        self.assertIn('Vero', msg_vero)

    def test_bloqueio_por_documento_usa_os_quando_informada(self) -> None:
        self.assertEqual(bloqueio_por_documento('11144477735', 'OSNIO1'), '')
        self.assertIn('Vero', bloqueio_por_documento('11144477735', 'OSVERO1'))

    def test_filtro_lote_exclui_operadora_sem_pap(self) -> None:
        ids = set(
            Venda.objects.filter(filtro_vendas_com_pap()).values_list('id', flat=True)
        )
        self.assertEqual(ids, {self.venda_nio.id})
