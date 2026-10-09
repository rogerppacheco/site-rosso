"""Testes da consulta STATUS PAP da Esteira."""
from __future__ import annotations

import threading
from datetime import timedelta
from unittest import mock

from django.core.exceptions import SynchronousOnlyOperation
from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from crm_app.esteira_consulta_status_pap_service import (
    _recarregar_venda_elegivel,
    _run_django_sync,
    ids_fila_consulta_aba,
    mensagem_erro_consulta_pap_para_usuario,
    queryset_vendas_consulta_aba,
)
from crm_app.esteira_sync_status_pap_service import (
    encerrar_execucoes_orfas,
    execucao_em_andamento,
)
from crm_app.models import Cliente, Operadora, Plano, StatusCRM, SyncStatusEsteiraExecucao, Venda
from crm_app.utils import _esteira_permite_sync_status_pap
from usuarios.models import Usuario


class ConsultaStatusPapFilaTodosTests(TestCase):
    def setUp(self) -> None:
        self.usuario = Usuario.objects.create_user(username='filatodos', password='teste')
        self.cliente = Cliente.objects.create(nome_razao_social='Cliente', cpf_cnpj='52998224725')
        nio = Operadora.objects.create(nome='NIO', usa_pap_nio=True)
        vero = Operadora.objects.create(nome='Vero', usa_pap_nio=False)
        self.plano_nio = Plano.objects.create(nome='NIO 600', valor=100, operadora=nio)
        self.plano_vero = Plano.objects.create(nome='VERO 700', valor=120, operadora=vero)
        self.st_agendado = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        self.st_pend = StatusCRM.objects.create(nome='PENDENCIADA', tipo='Esteira', estado='ABERTO')
        self.st_outro = StatusCRM.objects.create(nome='NÃO CONSTA NA OSAB', tipo='Esteira', estado='ABERTO')
        self.st_cancelada = StatusCRM.objects.create(nome='CANCELADA', tipo='Esteira', estado='ABERTO')
        self.st_instalada = StatusCRM.objects.create(nome='INSTALADA', tipo='Esteira', estado='FECHADO')

    def _venda(self, status, os_num='', **extra) -> Venda:
        extra.setdefault('plano', self.plano_nio)
        return Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente,
            status_esteira=status,
            ordem_servico=os_num,
            **extra,
        )

    def test_fila_so_pega_operadora_com_pap_nio(self) -> None:
        nio = self._venda(self.st_outro, 'OS1')
        self._venda(self.st_outro, 'OS2', plano=self.plano_vero)
        self._venda(self.st_outro, 'OS3', plano=None)
        ids = set(queryset_vendas_consulta_aba({'aba': 'TODOS'}).values_list('id', flat=True))
        self.assertEqual(ids, {nio.id})

    def test_sync_pap_atualiza_qualquer_status_aberto(self) -> None:
        self.assertTrue(_esteira_permite_sync_status_pap(self._venda(self.st_outro, 'A1')))
        self.assertTrue(_esteira_permite_sync_status_pap(self._venda(self.st_agendado, 'A2')))
        self.assertTrue(_esteira_permite_sync_status_pap(self._venda(self.st_pend, 'A3')))
        self.assertFalse(_esteira_permite_sync_status_pap(self._venda(self.st_instalada, 'A4')))
        self.assertFalse(_esteira_permite_sync_status_pap(self._venda(self.st_cancelada, 'A5')))

    def test_todos_pega_tudo_com_os_sem_filtrar_status(self) -> None:
        ag = self._venda(self.st_agendado, 'OS1')
        pend = self._venda(self.st_pend, 'OS2')
        outro = self._venda(self.st_outro, 'OS3')
        self._venda(self.st_outro, '')
        self._venda(self.st_outro, '   ')
        self._venda(self.st_cancelada, 'OS4')
        self._venda(self.st_instalada, 'OS5')
        self._venda(self.st_agendado, 'OS6', ativo=False)

        ids = set(queryset_vendas_consulta_aba({'aba': 'TODOS'}).values_list('id', flat=True))
        self.assertEqual(ids, {ag.id, pend.id, outro.id})

    def test_todos_ignora_filtros_extras(self) -> None:
        ag = self._venda(self.st_agendado, 'OS1')
        outro = self._venda(self.st_outro, 'OS2')
        filtros = {
            'aba': 'TODOS',
            'busca': 'nada-a-ver',
            'tipo_pendencia': 'TECNICA',
            'motivo_pendencia': '999',
            'colunas': {'vendedor': 'ninguem'},
        }
        ids = set(queryset_vendas_consulta_aba(filtros).values_list('id', flat=True))
        self.assertEqual(ids, {ag.id, outro.id})

    def test_abas_especificas_continuam_restritas(self) -> None:
        ag = self._venda(self.st_agendado, 'OS1')
        pend = self._venda(self.st_pend, 'OS2')
        self._venda(self.st_outro, 'OS3')
        self.assertEqual(
            list(queryset_vendas_consulta_aba({'aba': 'AGENDADO'}).values_list('id', flat=True)),
            [ag.id],
        )
        self.assertEqual(
            list(queryset_vendas_consulta_aba({'aba': 'PENDEN'}).values_list('id', flat=True)),
            [pend.id],
        )
        self.assertFalse(queryset_vendas_consulta_aba({'aba': 'INSTALADAS'}).exists())

    def test_fila_nao_repete_mesma_os(self) -> None:
        self._venda(self.st_agendado, '0012345')
        self._venda(self.st_pend, '12345')
        self._venda(self.st_outro, 'OS9')
        self.assertEqual(len(ids_fila_consulta_aba({'aba': 'TODOS'})), 2)

    def test_venda_que_sai_da_aba_durante_lote_e_pulada(self) -> None:
        venda = self._venda(self.st_outro, 'OS1')
        filtros = {'aba': 'TODOS'}
        self.assertIsNotNone(_recarregar_venda_elegivel(venda.id, filtros))
        venda.status_esteira = self.st_cancelada
        venda.save(update_fields=['status_esteira'])
        self.assertIsNone(_recarregar_venda_elegivel(venda.id, filtros))


class ConsultaStatusPapMensagemTests(SimpleTestCase):
    def test_mensagem_erro_too_many_clients(self) -> None:
        msg = mensagem_erro_consulta_pap_para_usuario(
            'FATAL:  sorry, too many clients already'
        )
        self.assertIn('sem conexões livres', msg)
        self.assertNotIn('too many clients', msg.lower())

    def test_mensagem_erro_preserva_texto_desconhecido(self) -> None:
        self.assertEqual(
            mensagem_erro_consulta_pap_para_usuario('login inválido'),
            'login inválido',
        )

    def test_run_django_sync_reutiliza_thread_atual(self) -> None:
        main = threading.get_ident()
        seen = {'ident': None}

        def fn() -> str:
            seen['ident'] = threading.get_ident()
            return 'ok'

        self.assertEqual(_run_django_sync(fn), 'ok')
        self.assertEqual(seen['ident'], main)

    def test_run_django_sync_cai_para_thread_apos_async_unsafe(self) -> None:
        main = threading.get_ident()
        seen: list[int] = []

        def fn() -> str:
            ident = threading.get_ident()
            seen.append(ident)
            if ident == main:
                raise SynchronousOnlyOperation('unsafe')
            return 'ok'

        self.assertEqual(_run_django_sync(fn), 'ok')
        self.assertNotEqual(seen[-1], main)

    def test_run_django_sync_retenta_too_many_clients(self) -> None:
        calls = {'n': 0}

        def flaky() -> str:
            calls['n'] += 1
            if calls['n'] < 3:
                raise OperationalError('FATAL: sorry, too many clients already')
            return 'ok'

        with mock.patch('crm_app.db_resilience.time.sleep'):
            self.assertEqual(_run_django_sync(flaky), 'ok')
        self.assertEqual(calls['n'], 3)


class ConsultaStatusPapExecucaoTests(TestCase):
    def test_pendente_recente_conta_como_em_andamento(self) -> None:
        execucao = SyncStatusEsteiraExecucao.objects.create(
            modo=SyncStatusEsteiraExecucao.MODO_CONSULTA_ABA,
            status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
            total_pedidos=10,
        )
        atual = execucao_em_andamento()
        self.assertIsNotNone(atual)
        self.assertEqual(atual.id, execucao.id)

    def test_pendente_antigo_e_encerrado_como_erro(self) -> None:
        execucao = SyncStatusEsteiraExecucao.objects.create(
            modo=SyncStatusEsteiraExecucao.MODO_CONSULTA_ABA,
            status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
            total_pedidos=10,
        )
        SyncStatusEsteiraExecucao.objects.filter(pk=execucao.pk).update(
            iniciado_em=timezone.now() - timedelta(minutes=10),
        )
        encerradas = encerrar_execucoes_orfas()
        execucao.refresh_from_db()
        self.assertGreaterEqual(encerradas, 1)
        self.assertEqual(execucao.status, SyncStatusEsteiraExecucao.STATUS_ERRO)
        self.assertIsNone(execucao_em_andamento())
