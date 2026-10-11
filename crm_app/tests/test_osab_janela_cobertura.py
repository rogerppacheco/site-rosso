"""Marcação NÃO CONSTA NA OSAB restrita ao período coberto pela planilha importada."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest import mock

import pandas as pd
from django.db.backends.utils import CursorWrapper
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from crm_app.models import (
    Cliente,
    ImportacaoOsab,
    LogImportacaoOSAB,
    Operadora,
    Plano,
    StatusCRM,
    Venda,
)
from crm_app.views import ImportacaoOsabView
from usuarios.models import Usuario


class JanelaCoberturaOsabTests(SimpleTestCase):
    def test_fim_e_dia_anterior_ao_dt_ref(self) -> None:
        df = pd.DataFrame({
            'DATA_ABERTURA': [datetime(2026, 9, 1, 10), datetime(2026, 10, 8, 18)],
            'DT_REF': [date(2026, 10, 9), date(2026, 10, 9)],
        })
        self.assertEqual(
            ImportacaoOsabView._janela_cobertura_osab(df),
            (date(2026, 9, 1), date(2026, 10, 8)),
        )

    def test_sem_dt_ref_usa_maior_abertura(self) -> None:
        df = pd.DataFrame({
            'DATA_ABERTURA': [datetime(2026, 8, 3, 9), datetime(2026, 8, 29, 17)],
        })
        self.assertEqual(
            ImportacaoOsabView._janela_cobertura_osab(df),
            (date(2026, 8, 3), date(2026, 8, 29)),
        )

    def test_sem_abertura_retorna_none(self) -> None:
        df = pd.DataFrame({'DT_REF': [date(2026, 10, 9)], 'DATA_ABERTURA': [None]})
        self.assertIsNone(ImportacaoOsabView._janela_cobertura_osab(df))


_execute_original = CursorWrapper.execute


def _execute_sem_set_local(self, sql, params=None):
    if str(sql).lstrip().upper().startswith('SET LOCAL'):
        return None
    return _execute_original(self, sql, params)


@mock.patch.object(CursorWrapper, 'execute', _execute_sem_set_local)
@mock.patch.object(ImportacaoOsabView, '_sincronizar_seq_historico', lambda self: None)
class MarcacaoAusentesOsabTests(TestCase):
    def setUp(self) -> None:
        self.usuario = Usuario.objects.create_user(username='osabjanela', password='teste')
        self.cliente = Cliente.objects.create(nome_razao_social='Cliente', cpf_cnpj='52998224725')
        operadora = Operadora.objects.create(nome='NIO')
        self.plano = Plano.objects.create(nome='NIO 600', valor=100, operadora=operadora)
        self.st_agendado = StatusCRM.objects.create(nome='AGENDADO', tipo='Esteira', estado='ABERTO')
        self.st_nao = StatusCRM.objects.create(nome='NÃO CONSTA NA OSAB', tipo='Esteira', estado='ABERTO')
        ImportacaoOsab.objects.create(documento='90000001')
        self.log = LogImportacaoOSAB.objects.create(nome_arquivo='osab.xlsb', status='PROCESSANDO')
        self.hoje = timezone.localdate()

    def _venda(self, os_num: str, dias_atras: int) -> Venda:
        aberta = timezone.make_aware(datetime.combine(self.hoje - timedelta(days=dias_atras), datetime.min.time()))
        return Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente,
            plano=self.plano,
            status_esteira=self.st_agendado,
            ordem_servico=os_num,
            data_abertura=aberta,
        )

    def _marcar(self, inicio_dias: int, fim_dias: int) -> dict:
        janela = (self.hoje - timedelta(days=inicio_dias), self.hoje - timedelta(days=fim_dias))
        return ImportacaoOsabView()._marcar_vendas_ausentes_na_osab(
            self.log.id, 10, self.usuario, pedidos_validos_planilha=10, janela_cobertura=janela,
        )

    def test_so_marca_vendas_dentro_da_cobertura(self) -> None:
        dentro = self._venda('80000001', dias_atras=5)
        depois = self._venda('80000002', dias_atras=2)
        antes = self._venda('80000003', dias_atras=40)
        consta = self._venda('90000001', dias_atras=5)

        out = self._marcar(inicio_dias=30, fim_dias=3)

        for v in (dentro, depois, antes, consta):
            v.refresh_from_db()
        self.assertEqual(dentro.status_esteira, self.st_nao)
        self.assertEqual(depois.status_esteira, self.st_agendado)
        self.assertEqual(antes.status_esteira, self.st_agendado)
        self.assertEqual(consta.status_esteira, self.st_agendado)
        self.assertEqual(out['crm_sem_osab_nao_consta'], 1)
        self.assertEqual(out['crm_sem_osab_ignoradas_apos_cobertura'], 1)
        self.assertEqual(out['crm_sem_osab_ignoradas_antes_cobertura'], 1)

    def test_sem_cobertura_nao_marca_nada(self) -> None:
        venda = self._venda('80000001', dias_atras=5)
        out = ImportacaoOsabView()._marcar_vendas_ausentes_na_osab(
            self.log.id, 10, self.usuario, pedidos_validos_planilha=10, janela_cobertura=None,
        )
        venda.refresh_from_db()
        self.assertEqual(venda.status_esteira, self.st_agendado)
        self.assertTrue(out['pos_processamento_ausentes_pulado'])
