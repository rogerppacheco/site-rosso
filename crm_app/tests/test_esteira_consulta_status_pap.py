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
    _run_django_sync,
    mensagem_erro_consulta_pap_para_usuario,
)
from crm_app.esteira_sync_status_pap_service import (
    encerrar_execucoes_orfas,
    execucao_em_andamento,
)
from crm_app.models import SyncStatusEsteiraExecucao


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
