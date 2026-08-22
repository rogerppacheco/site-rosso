"""Testes da persistência de e-mails recusados pelo PAP na análise de crédito."""

from __future__ import annotations

import asyncio
import threading

from django.test import SimpleTestCase, TestCase

from crm_app.models import EmailRecusadoPapCredito
from crm_app.services.credito_contato_repo import (
    RepositorioEmailsRecusadosPap,
    executar_orm,
)


class ExecutarOrmTests(SimpleTestCase):
    def test_sem_event_loop_roda_na_thread_atual(self):
        atual = threading.current_thread().name

        self.assertEqual(executar_orm(lambda: threading.current_thread().name), atual)

    def test_com_event_loop_ativo_roda_em_outra_thread(self):
        atual = threading.current_thread().name

        async def dentro_do_loop() -> str:
            return executar_orm(lambda: threading.current_thread().name)

        self.assertNotEqual(asyncio.run(dentro_do_loop()), atual)

    def test_propaga_erro_da_thread(self):
        async def dentro_do_loop() -> None:
            def falhar() -> None:
                raise ValueError("erro na thread")

            executar_orm(falhar)

        with self.assertRaises(ValueError):
            asyncio.run(dentro_do_loop())


class RepositorioEmailsRecusadosPapTests(TestCase):
    def setUp(self) -> None:
        self.repositorio = RepositorioEmailsRecusadosPap()

    def test_registra_e_conta_ocorrencias(self):
        self.repositorio.registrar_email("Antigo@Live.com", "EMAIL_INVALIDO")
        self.repositorio.registrar_email("antigo@live.com", "EMAIL_INVALIDO")

        registro = EmailRecusadoPapCredito.objects.get(email="antigo@live.com")
        self.assertEqual(registro.ocorrencias, 2)
        self.assertEqual(registro.motivo, "EMAIL_INVALIDO")

    def test_consulta_devolve_apenas_os_recusados(self):
        EmailRecusadoPapCredito.objects.create(
            email="antigo@live.com", motivo="EMAIL_INVALIDO"
        )

        recusados = self.repositorio.emails_recusados(
            ["ANTIGO@live.com", "novo@dominio.com"]
        )

        self.assertEqual(recusados, {"antigo@live.com"})

    def test_lista_vazia_nao_consulta_banco(self):
        with self.assertNumQueries(0):
            self.assertEqual(self.repositorio.emails_recusados([]), set())

    def test_executor_padrao_roda_direto_sem_event_loop(self):
        self.repositorio.registrar_email("direto@live.com", "EMAIL_INVALIDO")

        self.assertTrue(
            EmailRecusadoPapCredito.objects.filter(email="direto@live.com").exists()
        )

    def test_executor_recebe_a_operacao_de_banco(self):
        chamadas: list[str] = []

        def executor(funcao):
            chamadas.append("executado")
            return funcao()

        repositorio = RepositorioEmailsRecusadosPap(executor=executor)
        repositorio.registrar_email("outro@live.com", "EMAIL_INVALIDO")

        self.assertEqual(chamadas, ["executado"])
        self.assertTrue(
            EmailRecusadoPapCredito.objects.filter(email="outro@live.com").exists()
        )

    def test_falha_de_banco_nao_propaga(self):
        def executor(_funcao):
            raise RuntimeError("banco indisponível")

        repositorio = RepositorioEmailsRecusadosPap(executor=executor)

        self.assertEqual(repositorio.emails_recusados(["x@y.com"]), set())
        repositorio.registrar_email("x@y.com", "EMAIL_INVALIDO")
