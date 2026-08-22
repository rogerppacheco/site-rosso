from django.test import SimpleTestCase

from crm_app.esteira_posso_antecipar_service import (
    deve_tentar_posso_antecipar,
    formatar_posso_antecipar_exibicao,
    montar_botoes_posso_antecipar,
    parse_button_id_posso_antecipar,
    parse_resposta_posso_antecipar_vendedor,
    telefone_vendedor_para_envio_sistema,
)


class _VendaStub:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _VendedorStub:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TelefoneVendedorEnvioTests(SimpleTestCase):
    def test_usa_whatsapp_1_do_vendedor(self):
        vendedor = _VendedorStub(username='joao', tel_whatsapp='31999887766')
        venda = _VendaStub(vendedor=vendedor, telefone1='21988887777')
        tel, err = telefone_vendedor_para_envio_sistema(venda)
        self.assertEqual('', err)
        self.assertEqual('31999887766', tel)

    def test_nao_usa_telefone1_da_venda(self):
        vendedor = _VendedorStub(username='joao', tel_whatsapp='', tel_whatsapp_2='21988887777')
        venda = _VendaStub(vendedor=vendedor, telefone1='21988887777')
        tel, err = telefone_vendedor_para_envio_sistema(venda)
        self.assertIsNone(tel)
        self.assertIn('WhatsApp 1', err)

    def test_rejeita_whatsapp_igual_telefone_cliente(self):
        vendedor = _VendedorStub(username='joao', tel_whatsapp='5521988887777')
        venda = _VendaStub(vendedor=vendedor, telefone1='21988887777')
        tel, err = telefone_vendedor_para_envio_sistema(venda)
        self.assertIsNone(tel)
        self.assertIn('coincide', err.lower())


class FormatacaoExibicaoPossoAnteciparTests(SimpleTestCase):
    def test_sim_manha(self):
        v = _VendaStub(vendedor_pode_antecipar=True, vendedor_pode_antecipar_turno='MANHA')
        self.assertEqual(formatar_posso_antecipar_exibicao(v), 'Sim, Manhã')

    def test_aguardando(self):
        from django.utils import timezone
        v = _VendaStub(
            data_solicitacao_posso_antecipar=timezone.now(),
            data_resposta_posso_antecipar=None,
        )
        self.assertEqual(formatar_posso_antecipar_exibicao(v), 'Aguardando')


class BotaoPossoAnteciparTests(SimpleTestCase):
    def test_nao_tenta_texto_longo_explicativo(self):
        self.assertFalse(deve_tentar_posso_antecipar('Hoje ele nao ta disponível e domingo'))
        self.assertFalse(deve_tentar_posso_antecipar('Status'))
        self.assertFalse(deve_tentar_posso_antecipar('1'))
        self.assertFalse(deve_tentar_posso_antecipar('03642021654'))
        self.assertFalse(deve_tentar_posso_antecipar('Bom dia'))

    def test_tenta_botao_pa(self):
        self.assertTrue(deve_tentar_posso_antecipar('', button_id='pa_99_sim_manha'))
        self.assertTrue(deve_tentar_posso_antecipar('Sim, manhã'))
        self.assertTrue(deve_tentar_posso_antecipar('Não #6735'))

    def test_botoes_tres_opcoes_com_id_pedido(self):
        botoes = montar_botoes_posso_antecipar(6735)
        self.assertEqual(3, len(botoes))
        self.assertEqual('pa_6735_sim_manha', botoes[0]['id'])
        self.assertEqual('Sim, manhã', botoes[0]['label'])

    def test_parse_botao_sim_tarde(self):
        r = parse_button_id_posso_antecipar('pa_6735_sim_tarde')
        self.assertEqual(6735, r['venda_id'])
        self.assertTrue(r['pode'])
        self.assertEqual('TARDE', r['turno'])

    def test_parse_botao_nao(self):
        r = parse_button_id_posso_antecipar('pa_99_nao')
        self.assertEqual(99, r['venda_id'])
        self.assertFalse(r['pode'])


class ParseRespostaPossoAnteciparTests(SimpleTestCase):
    def test_sim_manha(self):
        r = parse_resposta_posso_antecipar_vendedor('Sim, manhã')
        self.assertTrue(r['pode'])
        self.assertEqual(r['turno'], 'MANHA')
        self.assertEqual(r['observacao'], '')

    def test_sim_tarde(self):
        r = parse_resposta_posso_antecipar_vendedor('Sim, tarde')
        self.assertTrue(r['pode'])
        self.assertEqual(r['turno'], 'TARDE')

    def test_nao(self):
        r = parse_resposta_posso_antecipar_vendedor('Não')
        self.assertFalse(r['pode'])
        self.assertIsNone(r['turno'])

    def test_nao_com_observacao(self):
        r = parse_resposta_posso_antecipar_vendedor('Não, cliente viaja amanhã')
        self.assertFalse(r['pode'])
        self.assertIn('cliente viaja', r['observacao'].lower())

    def test_sim_sem_turno_guarda_mensagem(self):
        r = parse_resposta_posso_antecipar_vendedor('Sim')
        self.assertTrue(r['pode'])
        self.assertIsNone(r['turno'])
        self.assertEqual(r['resposta_completa'], 'Sim')

    def test_texto_livre_sem_sim_nao(self):
        r = parse_resposta_posso_antecipar_vendedor('Talvez depois')
        self.assertIsNone(r['pode'])
        self.assertEqual(r['resposta_completa'], 'Talvez depois')

    def test_texto_longo_com_nao_no_meio_nao_e_recusa(self):
        r = parse_resposta_posso_antecipar_vendedor('Hoje ele nao ta disponível e domingo')
        self.assertIsNone(r['pode'])
        self.assertIn('dispon', r['observacao'].lower())
