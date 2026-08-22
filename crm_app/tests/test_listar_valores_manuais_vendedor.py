from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from crm_app.services.comissao_matriz_service import listar_valores_manuais_vendedor


class ListarValoresManuaisVendedorTest(SimpleTestCase):
    def test_inclui_ativos_e_inativos_com_valor(self) -> None:
        plano_ativo = SimpleNamespace(
            id=1, nome='NIO 600MB', ativo=True, operadora_id=1,
            operadora=SimpleNamespace(nome='NIO'),
        )
        plano_inativo = SimpleNamespace(
            id=2, nome='NIO 700MB', ativo=False, operadora_id=1,
            operadora=SimpleNamespace(nome='NIO'),
        )
        row_inativo = SimpleNamespace(
            plano_id=2,
            plano=plano_inativo,
            valor_pap=Decimal('190.00'),
            valor_cnpj=None,
        )
        config = SimpleNamespace(id=10)

        qs_planos = MagicMock()
        qs_planos.select_related.return_value.order_by.return_value = [plano_ativo]

        qs_existentes = MagicMock()
        qs_existentes.select_related.return_value = [row_inativo]

        with (
            patch('crm_app.services.comissao_matriz_service.Plano') as PlanoMock,
            patch(
                'crm_app.services.comissao_matriz_service.PlanoValoresComissaoVendedor'
            ) as PvcMock,
        ):
            PlanoMock.objects.filter.return_value = qs_planos
            PvcMock.objects.filter.return_value = qs_existentes
            out = listar_valores_manuais_vendedor(config)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['plano_id'], 1)
        self.assertTrue(out[0]['plano_ativo'])
        self.assertEqual(out[1]['plano_id'], 2)
        self.assertFalse(out[1]['plano_ativo'])
        self.assertEqual(out[1]['valor_pap'], 190.0)

    def test_ignora_inativo_sem_valor(self) -> None:
        plano_ativo = SimpleNamespace(
            id=1, nome='NIO 600MB', ativo=True, operadora_id=None, operadora=None,
        )
        plano_inativo = SimpleNamespace(
            id=2, nome='NIO 700MB', ativo=False, operadora_id=None, operadora=None,
        )
        row_vazio = SimpleNamespace(
            plano_id=2, plano=plano_inativo, valor_pap=None, valor_cnpj=None,
        )
        config = SimpleNamespace(id=10)

        qs_planos = MagicMock()
        qs_planos.select_related.return_value.order_by.return_value = [plano_ativo]
        qs_existentes = MagicMock()
        qs_existentes.select_related.return_value = [row_vazio]

        with (
            patch('crm_app.services.comissao_matriz_service.Plano') as PlanoMock,
            patch(
                'crm_app.services.comissao_matriz_service.PlanoValoresComissaoVendedor'
            ) as PvcMock,
        ):
            PlanoMock.objects.filter.return_value = qs_planos
            PvcMock.objects.filter.return_value = qs_existentes
            out = listar_valores_manuais_vendedor(config)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['plano_id'], 1)
