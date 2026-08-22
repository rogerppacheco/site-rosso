from datetime import date

from django.test import SimpleTestCase
from django.utils import timezone

from crm_app.esteira_posso_reagendar_service import (
    consultor_respondeu_reagendar,
    formatar_reagendar_consultor_exibicao,
    formatar_reagendar_consultor_exibicao_com_consultor,
    gerar_tres_datas_opcao,
    montar_botoes_sim_nao,
    parse_button_id_posso_reagendar,
    deve_tentar_posso_reagendar,
)


class _VendaStub:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _VendedorStub:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FormatacaoReagendarConsultorTests(SimpleTestCase):
    def test_exibicao_com_consultor_sim_data_turno(self):
        v = _VendaStub(
            vendedor=_VendedorStub(username='FERNANDA'),
            consultor_pode_reagendar=True,
            consultor_reagendar_data=date(2026, 6, 1),
            consultor_reagendar_turno='MANHA',
        )
        self.assertEqual('FERNANDA: Sim — 01/06 Manhã', formatar_reagendar_consultor_exibicao_com_consultor(v))

    def test_consultor_respondeu_quando_ha_data_resposta(self):
        v = _VendaStub(
            vendedor=_VendedorStub(username='GLEICE'),
            data_resposta_reagendar_consultor=timezone.now(),
        )
        self.assertEqual('GLEICE', consultor_respondeu_reagendar(v))

    def test_consultor_respondeu_vazio_sem_resposta(self):
        v = _VendaStub(vendedor=_VendedorStub(username='GLEICE'))
        self.assertEqual('', consultor_respondeu_reagendar(v))

    def test_aguardando(self):
        v = _VendaStub(
            data_solicitacao_reagendar_consultor=timezone.now(),
            data_resposta_reagendar_consultor=None,
        )
        self.assertEqual('Aguardando', formatar_reagendar_consultor_exibicao(v))


class ParseBotaoPossoReagendarTests(SimpleTestCase):
    def test_sim(self):
        r = parse_button_id_posso_reagendar('pr_100_sim')
        self.assertEqual(100, r['venda_id'])
        self.assertEqual('sim', r['acao'])

    def test_data(self):
        r = parse_button_id_posso_reagendar('pr_100_dt_20260615')
        self.assertEqual(date(2026, 6, 15), r['data'])

    def test_turno_tarde(self):
        r = parse_button_id_posso_reagendar('pr_50_tarde')
        self.assertEqual('TARDE', r['turno'])


class BotoesPossoReagendarTests(SimpleTestCase):
    def test_botoes_sim_nao(self):
        b = montar_botoes_sim_nao(42)
        self.assertEqual(2, len(b))
        self.assertEqual('pr_42_sim', b[0]['id'])

    def test_tres_datas(self):
        datas = gerar_tres_datas_opcao(a_partir_de=date(2026, 6, 1))
        self.assertEqual(3, len(datas))
        self.assertEqual(date(2026, 6, 1), datas[0])

    def test_deve_tentar_botao_pr(self):
        self.assertTrue(deve_tentar_posso_reagendar('', button_id='pr_100_sim'))
