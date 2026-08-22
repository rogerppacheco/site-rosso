from datetime import date, timedelta

from django.test import SimpleTestCase

from crm_app.performance_helpers import (
    calcular_dvu,
    calcular_pct_representatividade,
    cores_linha_performance,
    cores_linha_semanal,
    dias_decorridos_semana,
    indice_faixa_comissao,
    limite_peso_mes,
    media_diaria_semana_referencia,
    ordenar_lista_performance,
    ordem_cluster_performance,
    tipo_peso_gestao,
)
from core.services.calendario_fiscal_service import (
    fracao_dia_corrente,
    peso_unitario_dia,
    somar_pesos_periodo,
)


class _RegraStub:
    def __init__(self, pk, perfil=None, vendedor_id=None, min_v=0, max_v=99999):
        self.pk = pk
        self.id = pk
        self.perfil = perfil
        self.vendedor_id = vendedor_id
        self.min_vendas = min_v
        self.max_vendas = max_v


class PerformanceHelpersTests(SimpleTestCase):
    def test_ordem_cluster(self):
        self.assertEqual(ordem_cluster_performance('CLUSTER_1'), 1)
        self.assertEqual(ordem_cluster_performance('CLUSTER_2'), 2)
        self.assertEqual(ordem_cluster_performance('CLUSTER_3'), 3)
        self.assertEqual(ordem_cluster_performance(''), 99)

    def test_cores_faixas_hoje(self):
        self.assertEqual(cores_linha_performance(0)[0], (248, 215, 218))
        self.assertEqual(cores_linha_performance(2)[0], (255, 243, 205))
        self.assertEqual(cores_linha_performance(5)[0], (207, 226, 255))
        self.assertEqual(cores_linha_performance(6)[0], (20, 108, 67))

    def test_ordenacao_cluster_nome(self):
        lista = [
            {'nome': 'ZARA', 'cluster': 'CLUSTER_3'},
            {'nome': 'ANA', 'cluster': 'CLUSTER_1'},
            {'nome': 'BOB', 'cluster': 'CLUSTER_2'},
        ]
        ordenada = ordenar_lista_performance(lista)
        self.assertEqual([x['nome'] for x in ordenada], ['ANA', 'BOB', 'ZARA'])

    def test_dias_decorridos_semana(self):
        seg = date(2026, 5, 25)
        sab = seg + timedelta(days=5)
        self.assertEqual(dias_decorridos_semana(seg, sab, seg), 1)
        self.assertEqual(dias_decorridos_semana(seg, sab, seg + timedelta(days=2)), 3)
        self.assertEqual(dias_decorridos_semana(seg, sab, sab + timedelta(days=1)), 6)

    def test_media_semanal_cores(self):
        self.assertEqual(media_diaria_semana_referencia(14, 3), 5)
        self.assertEqual(cores_linha_semanal(14, 3)[0], cores_linha_performance(5)[0])

    def test_indice_faixa_vendedor(self):
        ctx = {
            'regras_perfil': [
                _RegraStub(1, perfil='Vendedor', min_v=1, max_v=20),
                _RegraStub(2, perfil='Vendedor', min_v=21, max_v=39),
                _RegraStub(3, perfil='Vendedor', min_v=51, max_v=99999),
            ],
            'regras_vendedor': {},
        }
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 0), -1)
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 10), 0)
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 25), 1)
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 60), 2)

    def test_calcular_dvu(self):
        self.assertEqual(calcular_dvu(10, 2.5), 4.0)
        self.assertEqual(calcular_dvu(0, 5), 0.0)
        self.assertEqual(calcular_dvu(7, 0), 0.0)
        self.assertEqual(calcular_dvu(5, 3), 1.67)

    def test_limite_peso_mes(self):
        inicio = date(2026, 7, 1)
        fim = date(2026, 7, 31)
        self.assertEqual(limite_peso_mes(inicio, fim, date(2026, 7, 12)), date(2026, 7, 12))
        self.assertEqual(limite_peso_mes(inicio, fim, date(2026, 8, 1)), fim)

    def test_tipo_peso_gestao(self):
        self.assertEqual(tipo_peso_gestao('BRUTA'), 'VB')
        self.assertEqual(tipo_peso_gestao('INSTALADA'), 'GR')

    def test_somar_pesos_periodo_semana(self):
        inicio = date(2026, 7, 6)
        fim = date(2026, 7, 11)
        limite = date(2026, 7, 8)
        peso = somar_pesos_periodo(inicio, fim, limite=limite, tipo='VB')
        self.assertEqual(peso, 3.0)

    def test_calcular_pct_representatividade(self):
        self.assertEqual(calcular_pct_representatividade(25, 100), 25.0)
        self.assertEqual(calcular_pct_representatividade(0, 100), 0.0)
        self.assertEqual(calcular_pct_representatividade(10, 0), 0.0)

    def test_somar_pesos_fraciona_hoje(self):
        from datetime import datetime
        from django.utils import timezone

        dia = date(2026, 7, 8)
        agora = timezone.make_aware(datetime(2026, 7, 8, 12, 0, 0))
        peso = somar_pesos_periodo(
            dia,
            dia,
            limite=dia,
            tipo='VB',
            hoje_ref=dia,
            agora_local=agora,
            fracionar_hoje=True,
        )
        self.assertAlmostEqual(peso, 0.5, places=2)
