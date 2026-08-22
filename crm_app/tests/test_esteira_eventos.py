from datetime import date

from django.test import TestCase
from django.utils import timezone

from crm_app.esteira_eventos_utils import (
    ORIGEM_MANUAL,
    TIPO_AGENDAMENTO,
    TIPO_STATUS_ESTEIRA,
    registrar_e_salvar_eventos_venda_esteira,
    registrar_eventos_venda_esteira,
)
from crm_app.models import MotivoPendencia, StatusCRM, Venda, VendaEsteiraEvento
from usuarios.models import Perfil, Usuario
from crm_app.models import Cliente


class EsteiraEventosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil = Perfil.objects.create(cod_perfil='T', nome='Admin')
        cls.user = Usuario.objects.create_user(
            username='user_evt', password='SenhaSegura123', perfil=cls.perfil,
        )
        cls.cliente = Cliente.objects.create(cpf_cnpj='99988877766', nome_razao_social='CLI EVT')
        cls.st_cad = StatusCRM.objects.create(nome='CADASTRADA', tipo='Tratamento')
        cls.st_agend = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        cls.st_pend = StatusCRM.objects.create(nome='PENDENCIADA', tipo='Esteira', estado='ABERTO')
        cls.motivo = MotivoPendencia.objects.create(nome='SEM SLOT', tipo_pendencia='OPERADORA')

    def _venda(self, **kwargs):
        defaults = dict(
            vendedor=self.user,
            cliente=self.cliente,
            status_tratamento=self.st_cad,
            status_esteira=self.st_agend,
            ordem_servico='87654321',
            data_agendamento=date(2026, 5, 20),
            periodo_agendamento='MANHA',
            ativo=True,
        )
        defaults.update(kwargs)
        return Venda.objects.create(**defaults)

    def test_registra_mudanca_status_e_agendamento(self):
        v1 = self._venda()
        v1_antes = Venda.objects.get(pk=v1.pk)
        v1.status_esteira = self.st_pend
        v1.motivo_pendencia = self.motivo
        v1.data_agendamento = None
        v1.periodo_agendamento = None
        v1.save()

        n = registrar_e_salvar_eventos_venda_esteira(v1_antes, v1, ORIGEM_MANUAL, self.user)
        self.assertGreaterEqual(n, 2)
        self.assertTrue(
            VendaEsteiraEvento.objects.filter(venda=v1, tipo_evento=TIPO_STATUS_ESTEIRA).exists()
        )
        self.assertTrue(
            VendaEsteiraEvento.objects.filter(venda=v1, tipo_evento=TIPO_AGENDAMENTO).exists()
        )

    def test_nao_duplica_evento_identico(self):
        v = self._venda()
        antes = Venda.objects.get(pk=v.pk)
        eventos = registrar_eventos_venda_esteira(antes, v, ORIGEM_MANUAL, self.user)
        self.assertEqual(len(eventos), 0)
