# site-record/crm_app/tests.py

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse

# Importe os modelos necessários dos seus apps
from usuarios.models import Usuario, Perfil, PermissaoPerfil
from .models import Operadora, Plano, FormaPagamento, Cliente, Venda, StatusCRM

class VendaAPITest(APITestCase):
    """
    Suite de testes para a API de Vendas (VendaViewSet).
    """

    @classmethod
    def setUpTestData(cls):
        cls.perfil_consultor = Perfil.objects.create(nome='Consultor')
        cls.consultor = Usuario.objects.create_user(
            username='consultor_api',
            password='SenhaSegura123',
            perfil=cls.perfil_consultor,
            first_name='Carlos',
            last_name='Teste'
        )
        cls.operadora = Operadora.objects.create(nome='OI Fibra')
        cls.plano = Plano.objects.create(nome='500 Mega', valor=99.99, operadora=cls.operadora)
        cls.forma_pagamento = FormaPagamento.objects.create(nome='Boleto Bancário')
        StatusCRM.objects.create(nome="SEM TRATAMENTO", tipo="Tratamento")
        PermissaoPerfil.objects.create(
            perfil=cls.perfil_consultor,
            recurso='vendas',
            pode_criar=True,
            pode_ver=True
        )

    def setUp(self):
        self.client.force_authenticate(user=self.consultor)

    def test_criar_nova_venda_com_sucesso(self):
        """
        Testa se um consultor com permissão pode criar uma nova venda (POST).
        """
        url = reverse('venda-list')
        dados_venda = {
            "cliente_cpf_cnpj": "123.456.789-00",
            "cliente_nome_razao_social": "Maria da Silva Teste",
            "plano": self.plano.id,
            "forma_pagamento": self.forma_pagamento.id,
            "cep": "30110-000",
            "logradouro": "Avenida Principal",
            "numero_residencia": "123",
            "bairro": "Centro",
            "cidade": "Cidade de Teste",
            "estado": "TS",
            "ponto_referencia": "Em frente à praça central"
        }
        response = self.client.post(url, dados_venda, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Venda.objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 1)
        venda_criada = Venda.objects.get()
        self.assertEqual(venda_criada.vendedor, self.consultor)
        self.assertEqual(venda_criada.cliente.nome_razao_social, "MARIA DA SILVA TESTE")
        self.assertIsNotNone(venda_criada.status_tratamento)
        self.assertEqual(venda_criada.status_tratamento.nome, "SEM TRATAMENTO")

    def test_bloqueia_acesso_sem_autenticacao(self):
        """
        Testa se a API retorna erro 401 para usuários não autenticados.
        """
        self.client.force_authenticate(user=None)
        url = reverse('venda-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_falha_ao_criar_venda_com_dados_invalidos(self):
        """
        Testa se a API retorna erro 400 ao tentar criar uma venda sem um campo obrigatório.
        """
        url = reverse('venda-list')
        dados_venda_incompleta = {
            "cliente_cpf_cnpj": "987.654.321-00",
            "cliente_nome_razao_social": "Cliente Incompleto",
            # "plano": self.plano.id,  <-- CAMPO OBRIGATÓRIO AUSENTE
            "forma_pagamento": self.forma_pagamento.id,
            "cep": "30110-000",
            "logradouro": "Rua Teste",
            "numero_residencia": "456",
            "bairro": "Bairro Teste",
            "cidade": "Cidade Teste",
            "estado": "TS",
            "ponto_referencia": "Perto do rio"
        }
        response = self.client.post(url, dados_venda_incompleta, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Venda.objects.count(), 0)
        self.assertEqual(Cliente.objects.count(), 0)
        self.assertIn('plano', response.data)
# Adicione este método DENTRO da classe VendaAPITest, após os outros testes

    def test_atualizar_status_da_venda_e_gerar_historico(self):
        """
        Testa se a API permite a atualização (PATCH) de uma venda e se a lógica
        de negócio (criação de histórico) é executada corretamente.
        """
        # 1. SETUP: Criar a venda que será atualizada
        venda = Venda.objects.create(
            vendedor=self.consultor,
            cliente=Cliente.objects.create(cpf_cnpj="111.222.333-44", nome_razao_social="Cliente a ser atualizado"),
            plano=self.plano,
            forma_pagamento=self.forma_pagamento,
            status_tratamento=StatusCRM.objects.get(nome="SEM TRATAMENTO")
        )

        # Criar os status que serão usados na atualização
        status_cadastrada = StatusCRM.objects.create(nome="CADASTRADA", tipo="Tratamento")
        StatusCRM.objects.create(nome="AGENDADO", tipo="Esteira") # Status que deve ser ativado automaticamente

        # Precisamos dar permissão de edição (change) para o nosso consultor
        permissao = PermissaoPerfil.objects.get(perfil=self.perfil_consultor, recurso='vendas')
        permissao.pode_editar = True
        permissao.save()

        # A URL para detalhe/edição da venda específica
        url = reverse('venda-detail', kwargs={'pk': venda.pk})
        
        # Dados para a atualização via PATCH
        dados_atualizacao = {
            "status_tratamento": status_cadastrada.id
        }

        # 2. AÇÃO: Realizar a requisição PATCH
        response = self.client.patch(url, dados_atualizacao, format='json')

        # 3. VERIFICAÇÕES (Asserts)
        # Verifica se a requisição foi bem-sucedida
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Atualiza a instância da venda com os novos dados do banco
        venda.refresh_from_db()

        # Verifica se o status de tratamento foi atualizado
        self.assertEqual(venda.status_tratamento.nome, "CADASTRADA")
        
        # Verifica a lógica de negócio: o status da esteira foi auto-preenchido?
        self.assertIsNotNone(venda.status_esteira)
        self.assertEqual(venda.status_esteira.nome, "AGENDADO")

        # Verifica se o histórico de alteração foi criado
        self.assertEqual(venda.historico_alteracoes.count(), 1)
        historico = venda.historico_alteracoes.first()
        self.assertEqual(historico.usuario, self.consultor)