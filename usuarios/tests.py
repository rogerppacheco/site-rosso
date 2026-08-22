# site-record/usuarios/tests.py

from django.test import TestCase
from django.contrib.auth import get_user_model

# Importe os modelos que você vai precisar testar
from .models import Perfil, Usuario

class UsuarioModelTest(TestCase):
    """
    Suite de testes para o modelo Usuario.
    """

    @classmethod
    def setUpTestData(cls):
        """
        Configuração inicial que roda uma vez para todos os testes da classe.
        Ideal para criar objetos que não serão modificados nos testes.
        """
        # Cria um perfil para ser usado pelo usuário
        cls.perfil = Perfil.objects.create(nome='Consultor')
        
        # Cria um usuário de teste
        cls.usuario = Usuario.objects.create_user(
            username='consultor_teste',
            password='SenhaSegura123',
            first_name='João',
            last_name='Silva',
            email='joao.silva@teste.com',
            perfil=cls.perfil
        )

    def test_usuario_foi_criado_com_sucesso(self):
        """
        Verifica se os campos básicos do usuário foram salvos corretamente.
        """
        # Busca o usuário criado no banco de dados de teste
        usuario_no_banco = Usuario.objects.get(id=self.usuario.id)

        # self.assertEqual() verifica se os dois valores são iguais.
        # Se não forem, o teste falha.
        self.assertEqual(usuario_no_banco.username, 'consultor_teste')
        self.assertEqual(usuario_no_banco.first_name, 'João')
        self.assertEqual(usuario_no_banco.get_full_name(), 'João Silva') # Testa um método do modelo
        self.assertTrue(usuario_no_banco.is_active) # Verifica se o valor é True
        self.assertFalse(usuario_no_banco.is_staff) # Verifica se o valor é False

    def test_perfil_do_usuario_esta_correto(self):
        """
        Verifica se o relacionamento com o modelo Perfil está funcionando.
        """
        self.assertEqual(self.usuario.perfil.nome, 'Consultor')
        self.assertEqual(str(self.usuario.perfil), 'Consultor') # Testa o método __str__ do Perfil