"""Testes do isolamento global por operadora."""
from types import SimpleNamespace

from django.contrib.auth.models import Group
from django.test import TestCase

from crm_app.models import Cliente, Operadora, Plano, Venda
from crm_app.serializers import VendaCreateSerializer
from crm_app.services.escopo_operadora import (
    filtrar_planos_por_operadora,
    filtrar_vendas_por_operadora,
    usuario_pode_acessar_operadora,
    validar_plano_para_usuario,
)
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer


class EscopoOperadoraTest(TestCase):
    def setUp(self) -> None:
        self.nio = Operadora.objects.create(nome='NIO')
        self.vero = Operadora.objects.create(nome='Vero')
        self.plano_nio = Plano.objects.create(
            nome='NIO 600',
            valor=100,
            operadora=self.nio,
        )
        self.plano_vero = Plano.objects.create(
            nome='VERO 700',
            valor=120,
            operadora=self.vero,
        )
        self.usuario = Usuario.objects.create_user(
            username='restrito',
            password='teste',
        )
        self.cliente_nio = Cliente.objects.create(
            nome_razao_social='Cliente Nio',
            cpf_cnpj='52998224725',
        )
        self.cliente_vero = Cliente.objects.create(
            nome_razao_social='Cliente Vero',
            cpf_cnpj='11144477735',
        )
        self.cliente_sem_plano = Cliente.objects.create(
            nome_razao_social='Cliente Sem Plano',
            cpf_cnpj='12345678909',
        )
        self.venda_nio = Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente_nio,
            plano=self.plano_nio,
        )
        self.venda_vero = Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente_vero,
            plano=self.plano_vero,
        )
        self.venda_sem_plano = Venda.objects.create(
            vendedor=self.usuario,
            cliente=self.cliente_sem_plano,
            plano=None,
        )

    def test_campo_vazio_libera_todas_operadoras_mas_nao_sem_plano(self) -> None:
        planos = filtrar_planos_por_operadora(Plano.objects.all(), self.usuario)
        vendas = filtrar_vendas_por_operadora(Venda.objects.all(), self.usuario)

        self.assertSetEqual(
            set(planos.values_list('id', flat=True)),
            {self.plano_nio.id, self.plano_vero.id},
        )
        self.assertSetEqual(
            set(vendas.values_list('id', flat=True)),
            {self.venda_nio.id, self.venda_vero.id},
        )

    def test_usuario_restrito_enxerga_somente_operadora_marcada(self) -> None:
        self.usuario.operadoras_permitidas.set([self.nio])

        vendas = filtrar_vendas_por_operadora(Venda.objects.all(), self.usuario)

        self.assertSetEqual(
            set(vendas.values_list('id', flat=True)),
            {self.venda_nio.id},
        )
        self.assertTrue(usuario_pode_acessar_operadora(self.usuario, self.nio.id))
        self.assertFalse(usuario_pode_acessar_operadora(self.usuario, self.vero.id))

    def test_admin_enxerga_inclusive_venda_sem_plano(self) -> None:
        admin = Usuario.objects.create_user(username='admin_teste', password='teste')
        admin.groups.add(Group.objects.create(name='Admin'))
        admin.operadoras_permitidas.set([self.nio])

        vendas = filtrar_vendas_por_operadora(Venda.objects.all(), admin)

        self.assertEqual(vendas.count(), 3)

    def test_diretoria_respeita_operadoras_marcadas(self) -> None:
        diretoria = Usuario.objects.create_user(
            username='diretoria_teste',
            password='teste',
        )
        diretoria.groups.add(Group.objects.create(name='Diretoria'))
        diretoria.operadoras_permitidas.set([self.vero])

        vendas = filtrar_vendas_por_operadora(Venda.objects.all(), diretoria)

        self.assertSetEqual(
            set(vendas.values_list('id', flat=True)),
            {self.venda_vero.id},
        )

    def test_criacao_rejeita_plano_de_operadora_nao_permitida(self) -> None:
        self.usuario.operadoras_permitidas.set([self.nio])
        serializer = VendaCreateSerializer(
            data={
                'cliente_cpf_cnpj': '39053344705',
                'cliente_nome_razao_social': 'Cliente Teste',
                'cliente_email': '',
                'telefone1': '31999999999',
                'telefone2': '31988888888',
                'plano': self.plano_vero.id,
            },
            context={'request': SimpleNamespace(user=self.usuario)},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('plano', serializer.errors)

    def test_criacao_via_app_permite_sem_plano(self) -> None:
        """Via APP o plano é preenchido depois; não pode bloquear o cadastro inicial."""
        self.usuario.operadoras_permitidas.set([self.nio])
        serializer = VendaCreateSerializer(
            data={
                'cliente_cpf_cnpj': '39053344705',
                'cliente_nome_razao_social': 'Cliente App',
                'cliente_email': '',
                'telefone1': '31999999999',
                'telefone2': '31988888888',
                'forma_entrada': 'APP',
                'plano': None,
            },
            context={'request': SimpleNamespace(user=self.usuario)},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_criacao_sem_app_exige_plano(self) -> None:
        self.usuario.operadoras_permitidas.set([self.nio])
        serializer = VendaCreateSerializer(
            data={
                'cliente_cpf_cnpj': '39053344705',
                'cliente_nome_razao_social': 'Cliente Sem App',
                'cliente_email': 'cliente@teste.com',
                'telefone1': '31999999999',
                'telefone2': '31988888888',
                'forma_entrada': 'SEM_APP',
                'plano': None,
            },
            context={'request': SimpleNamespace(user=self.usuario)},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('plano', serializer.errors)

    def test_validar_plano_para_usuario_bloqueia_fora_do_escopo(self) -> None:
        self.usuario.operadoras_permitidas.set([self.nio])

        self.assertIsNone(validar_plano_para_usuario(self.usuario, self.plano_nio))
        self.assertIsNotNone(validar_plano_para_usuario(self.usuario, self.plano_vero))
        self.assertIsNotNone(validar_plano_para_usuario(self.usuario, None))

        admin = Usuario.objects.create_user(username='admin_plano', password='teste')
        admin.groups.add(Group.objects.get_or_create(name='Admin')[0])
        self.assertIsNone(validar_plano_para_usuario(admin, None))

    def test_gestor_restrito_nao_pode_liberar_todas_operadoras(self) -> None:
        self.usuario.operadoras_permitidas.set([self.nio])
        alvo = Usuario.objects.create_user(username='alvo', password='teste')
        serializer = UsuarioSerializer(
            alvo,
            data={'operadoras_permitidas': []},
            partial=True,
            context={'request': SimpleNamespace(user=self.usuario)},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('operadoras_permitidas', serializer.errors)

    def test_gestor_restrito_so_pode_delegar_seu_proprio_escopo(self) -> None:
        self.usuario.operadoras_permitidas.set([self.nio])
        alvo = Usuario.objects.create_user(username='alvo_2', password='teste')
        serializer = UsuarioSerializer(
            alvo,
            data={'operadoras_permitidas': [self.vero.id]},
            partial=True,
            context={'request': SimpleNamespace(user=self.usuario)},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('operadoras_permitidas', serializer.errors)
