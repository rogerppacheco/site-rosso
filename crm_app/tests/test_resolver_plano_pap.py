from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from crm_app.models import Operadora, Plano
from crm_app.services_sincronizacao import (
    _familia_plano_pap,
    _velocidade_mb_pap,
    resolver_plano_pap,
)


class PlanoPapParseTest(SimpleTestCase):
    def test_familia(self):
        self.assertEqual(_familia_plano_pap("Nio Fibra Essencial Especial"), "ESSENCIAL")
        self.assertEqual(_familia_plano_pap("Nio Fibra Super"), "SUPER")
        self.assertEqual(_familia_plano_pap("Nio Fibra Ultra - Especial"), "ULTRA")

    def test_velocidade(self):
        self.assertEqual(_velocidade_mb_pap("600 Mega"), 600)
        self.assertEqual(_velocidade_mb_pap("600 MEGA"), 600)
        self.assertEqual(_velocidade_mb_pap("800 Mega"), 800)
        self.assertEqual(_velocidade_mb_pap("1 Giga"), 1000)


class ResolverPlanoPapTest(TestCase):
    def setUp(self):
        op = Operadora.objects.create(nome="NIO")
        Plano.objects.create(
            nome="NIO FIBRA ESSENCIAL 500MB", ativo=True, valor=Decimal("99"), operadora=op
        )
        Plano.objects.create(
            nome="NIO FIBRA ESSENCIAL 600MB", ativo=True, valor=Decimal("110"), operadora=op
        )
        Plano.objects.create(
            nome="NIO FIBRA SUPER 700MB", ativo=False, valor=Decimal("90"), operadora=op
        )
        Plano.objects.create(
            nome="NIO FIBRA SUPER 800MB", ativo=True, valor=Decimal("135"), operadora=op
        )
        Plano.objects.create(
            nome="NIO FIBRA ULTRA 1GB", ativo=True, valor=Decimal("160"), operadora=op
        )
        Plano.objects.create(
            nome="NIO FIBRA ULTRA 1GB (SEM MESH)", ativo=True, valor=Decimal("150"), operadora=op
        )

    def test_essencial_600_nao_pega_500(self):
        p = resolver_plano_pap("Nio Fibra Essencial", "600 Mega")
        self.assertIsNotNone(p)
        self.assertIn("600", p.nome)

    def test_super_800_nao_pega_700(self):
        p = resolver_plano_pap("Nio Fibra Super", "800 Mega")
        self.assertIsNotNone(p)
        self.assertIn("800", p.nome)

    def test_ultra_especial_vai_para_mesh(self):
        p = resolver_plano_pap("Nio Fibra Ultra - Especial", "1 Giga", 75)
        self.assertIsNotNone(p)
        self.assertEqual(p.nome, "NIO FIBRA ULTRA 1GB")
        self.assertNotIn("SEM MESH", p.nome)

    def test_ultra_150_vai_para_sem_mesh(self):
        p = resolver_plano_pap("Nio Fibra Ultra", "1 Giga", 150)
        self.assertIsNotNone(p)
        self.assertIn("SEM MESH", p.nome)

    def test_ultra_135_vai_para_sem_mesh(self):
        p = resolver_plano_pap("Nio Fibra Ultra", "1 Giga", 135)
        self.assertIsNotNone(p)
        self.assertIn("SEM MESH", p.nome)

    def test_ultra_sem_valor_default_sem_mesh(self):
        p = resolver_plano_pap("Nio Fibra Ultra", "1 Giga")
        self.assertIsNotNone(p)
        self.assertIn("SEM MESH", p.nome)
