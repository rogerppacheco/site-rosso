from django.test import SimpleTestCase

from crm_app.whatsapp_webhook_fastpath import avaliar_fastpath_zapi


class WhatsappWebhookFastpathTests(SimpleTestCase):
    def test_ignora_grupo_sem_formato_gc(self):
        payload = {
            'isGroup': True,
            'phone': '120363349227318284-group',
            'type': 'ReceivedCallback',
            'text': {'message': 'Bom dia'},
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual(out['status'], 'ok')
        self.assertIn('grupo', out['mensagem'].lower())

    def test_grupo_com_resposta_gc_vai_para_handler(self):
        payload = {
            'isGroup': True,
            'phone': '120363349227318284-group',
            'participantPhone': '5531999999999',
            'type': 'ReceivedCallback',
            'text': {'message': '12345, antecipada'},
        }
        self.assertIsNone(avaliar_fastpath_zapi(payload))

    def test_ignora_from_me(self):
        payload = {
            'fromMe': True,
            'phone': '5511999999999',
            'text': {'message': 'oi'},
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual(out['status'], 'ok')
        self.assertIn('bot', out['mensagem'].lower())

    def test_mensagem_direta_nao_ignora(self):
        payload = {
            'phone': '5511999999999',
            'type': 'ReceivedCallback',
            'text': {'message': 'Fachada'},
        }
        self.assertIsNone(avaliar_fastpath_zapi(payload))

    def test_clique_botao_sem_texto_nao_ignora(self):
        """Clique em Sim/Não (posso reagendar/antecipar) chega sem texto — não descartar."""
        payload = {
            'phone': '553187970208',
            'type': 'ReceivedCallback',
            'referenceMessageId': '3EB02CC8F0B3F6DF9796D1',
            'buttonsResponseMessage': {
                'buttonId': 'pr_6695_sim',
                'message': 'Sim',
            },
        }
        self.assertIsNone(avaliar_fastpath_zapi(payload))

    def test_webhook_vazio_sem_botao_ignora(self):
        payload = {
            'phone': '553187970208',
            'type': 'ReceivedCallback',
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual('ok', out['status'])
        self.assertIn('conteúdo', out['mensagem'].lower())

    def test_ignora_telefone_bloqueado(self):
        payload = {
            'phone': '5512981750292',
            'type': 'ReceivedCallback',
            'text': {'message': 'Escolha um dos botões abaixo.'},
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual(out['status'], 'ok')
        self.assertIn('bloqueado', out['mensagem'].lower())

    def test_ignora_telefone_bloqueado_sem_prefixo_55(self):
        payload = {
            'phone': '12981750292',
            'type': 'ReceivedCallback',
            'text': {'message': 'Fachada'},
        }
        out = avaliar_fastpath_zapi(payload)
        self.assertEqual(out['status'], 'ok')
        self.assertIn('bloqueado', out['mensagem'].lower())
