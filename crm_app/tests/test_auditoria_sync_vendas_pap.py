"""Cruzamento da auditoria com o histórico PAP (esteira, reprova e duplicidade)."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APITestCase

from crm_app.auditoria_sync_vendas_pap import (
    resolver_status_reprova,
    sincronizar_vendas_com_pap,
)
from crm_app.historico_pap_service import _atualizar_payload_existente
from crm_app.models import Cliente, HistoricoAlteracaoVenda, HistoricoPapPedido, MotivoPendencia, StatusCRM, Venda
from usuarios.models import Perfil, Usuario

PROTOCOLO = "202610086964805597"


def _payload(pedido, primario, secundario="", os_inst="", data_inst="", periodo="", cpf="39053344705"):
    return {
        "numeroPedido": pedido,
        "chaveStatusPrimario": primario,
        "subStatus": secundario,
        "cpf": cpf,
        "cliente": "CLIENTE TESTE",
        "produtos": {
            "bandaLarga": {
                "osInstalacao": os_inst,
                "dataInstalacao": data_inst,
                "periodoInstalacao": periodo,
            }
        },
    }


class AuditoriaSyncVendasPapTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil = Perfil.objects.create(cod_perfil="AUD", nome="Auditoria")
        cls.perfil_vendedor = Perfil.objects.create(cod_perfil="VEND", nome="Vendedor")
        cls.usuario = Usuario.objects.create_user(
            username="auditor_sync_pap",
            password="SenhaSegura123",
            perfil=cls.perfil,
        )
        cls.vendedor = Usuario.objects.create_user(
            username="vendedor_sync_pap",
            password="SenhaSegura123",
            perfil=cls.perfil_vendedor,
        )
        cls.cliente = Cliente.objects.create(
            cpf_cnpj="39053344705",
            nome_razao_social="PATRICIA FERNANDA",
        )
        cls.outro_cliente = Cliente.objects.create(
            cpf_cnpj="52998224725",
            nome_razao_social="OUTRO CLIENTE",
        )
        cls.st_sem = StatusCRM.objects.create(nome="SEM TRATAMENTO", tipo="Tratamento", estado="ABERTO")
        cls.st_cad = StatusCRM.objects.create(nome="CADASTRADA", tipo="Tratamento", estado="FECHADO")
        cls.st_fechado = StatusCRM.objects.create(nome="DESISTENCIA", tipo="Tratamento", estado="FECHADO")
        cls.st_consta = StatusCRM.objects.create(nome="JÁ CONSTA PEDIDO", tipo="Tratamento", estado="FECHADO")
        cls.st_consta_curto = StatusCRM.objects.create(nome="CONSTA PEDIDO", tipo="Tratamento", estado="FECHADO")
        cls.st_dup = StatusCRM.objects.create(nome="DUPLICIDADE", tipo="Tratamento", estado="FECHADO")
        cls.st_agendado = StatusCRM.objects.create(nome="AGENDADO", tipo="Esteira", estado="ABERTO")
        cls.st_pendenciada = StatusCRM.objects.create(nome="PENDENCIADA", tipo="Esteira", estado="ABERTO")
        cls.motivo_7030 = MotivoPendencia.objects.create(
            nome="7030 - PENDENCIA POR FALTA DE SLOT",
            tipo_pendencia="OPERADORA",
        )

    def _venda(self, pedido, cliente=None, status=None, esteira=None, os_inst=""):
        return Venda.objects.create(
            vendedor=self.usuario,
            cliente=cliente or self.cliente,
            status_tratamento=status or self.st_sem,
            status_esteira=esteira,
            pedido_pap=pedido,
            ordem_servico=os_inst or None,
            forma_entrada="SEM_APP",
        )

    def _pap(self, pedido, **kwargs):
        return HistoricoPapPedido.objects.create(
            numero_pedido=pedido,
            tipo_venda="VENDA",
            status=kwargs.get("primario", ""),
            payload=_payload(pedido, **kwargs),
        )

    def _por_pedido(self, resultado, pedido):
        for grupo in ("esteira", "reprovadas", "inalteradas"):
            for item in resultado[grupo]:
                if item["pedido"] == pedido:
                    return grupo, item
        return None, None

    def test_pedido_gerado_vai_para_esteira(self):
        venda = self._venda(PROTOCOLO)
        self._pap(
            PROTOCOLO,
            primario="PEDIDO_GERADO",
            os_inst="08907507",
            data_inst="2026-10-10",
            periodo="Manhã",
        )
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        self.assertEqual(resultado["resumo"]["esteira"], 1)
        self.assertEqual(venda.status_tratamento_id, self.st_cad.id)
        self.assertEqual(venda.status_esteira_id, self.st_agendado.id)
        self.assertEqual(venda.ordem_servico, "08907507")
        self.assertEqual(venda.data_agendamento, date(2026, 10, 10))
        self.assertEqual(venda.periodo_agendamento, "MANHA")
        self.assertIsNone(venda.auditor_atual)
        self.assertTrue(
            HistoricoAlteracaoVenda.objects.filter(venda=venda, alteracoes__ordem_servico="08907507").exists()
        )

    def test_pedido_gerado_noite_grava_como_tarde(self):
        pedido = "202610086964805613"
        venda = self._venda(pedido)
        self._pap(
            pedido,
            primario="PEDIDO_GERADO",
            os_inst="11631911",
            data_inst="2026-10-08",
            periodo="NOITE",
        )
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "esteira")
        self.assertEqual(venda.periodo_agendamento, "TARDE")
        self.assertEqual(venda.ordem_servico, "11631911")
        self.assertEqual(venda.data_agendamento, date(2026, 10, 8))
        self.assertIn("Noite no PAP", item["detalhe"])

    def test_pedido_gerado_sem_turno_vai_pendencia_7030(self):
        venda = self._venda("202610086964805598")
        self._pap(
            "202610086964805598",
            primario="PEDIDO_GERADO",
            os_inst="08907508",
            data_inst="2026-10-10",
            periodo="",
        )
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, "202610086964805598")
        self.assertEqual(grupo, "esteira")
        self.assertEqual(venda.status_tratamento_id, self.st_cad.id)
        self.assertEqual(venda.status_esteira_id, self.st_pendenciada.id)
        self.assertEqual(venda.motivo_pendencia_id, self.motivo_7030.id)
        self.assertEqual(venda.ordem_servico, "08907508")
        self.assertEqual(venda.data_agendamento, date(2026, 10, 10))
        self.assertIsNone(venda.periodo_agendamento)
        self.assertIn("7030", item["detalhe"])
        self.assertIn("turno", item["detalhe"])

    def test_pedido_gerado_sem_data_nem_turno_vai_pendencia_7030(self):
        pedido = "202610064049582617"
        venda = self._venda(pedido)
        self._pap(pedido, primario="PEDIDO_GERADO", os_inst="11630001", data_inst="", periodo="")
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "esteira")
        self.assertEqual(venda.status_esteira_id, self.st_pendenciada.id)
        self.assertEqual(venda.motivo_pendencia_id, self.motivo_7030.id)
        self.assertIsNone(venda.data_agendamento)
        self.assertIn("data", item["detalhe"])

    def test_pedido_gerado_sem_os_nao_altera(self):
        venda = self._venda("202610066915805597")
        self._pap("202610066915805597", primario="PEDIDO_GERADO", os_inst="", data_inst="", periodo="")
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, "202610066915805597")
        self.assertEqual(grupo, "inalteradas")
        self.assertIn("O.S. instalação", item["detalhe"])
        self.assertIsNone(venda.status_esteira_id)

    def test_agenda_incompleta_sem_motivo_7030_nao_altera(self):
        self.motivo_7030.delete()
        venda = self._venda("202610068776805597")
        self._pap(
            "202610068776805597",
            primario="PEDIDO_GERADO",
            os_inst="11630002",
            data_inst="",
            periodo="Manhã",
        )
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, "202610068776805597")
        self.assertEqual(grupo, "inalteradas")
        self.assertIn("7030", item["detalhe"])
        self.assertIsNone(venda.status_esteira_id)

    def test_os_ja_cadastrada_nao_avanca(self):
        self._venda(
            "202610086964805610",
            cliente=self.outro_cliente,
            status=self.st_cad,
            esteira=self.st_agendado,
            os_inst="08907509",
        )
        venda = self._venda("202610086964805599")
        self._pap(
            "202610086964805599",
            primario="PEDIDO_GERADO",
            os_inst="08907509",
            data_inst="10/10/2026",
            periodo="Tarde",
        )
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, "202610086964805599")
        self.assertEqual(grupo, "inalteradas")
        self.assertIn("já foi cadastrado", item["detalhe"])
        self.assertEqual(venda.status_tratamento_id, self.st_sem.id)

    def test_venda_nao_confirmada_os_em_aberto_vira_consta_pedido(self):
        pedido = "202610086964805600"
        venda = self._venda(pedido)
        self._pap(pedido, primario="VENDA_NAO_CONFIRMADA", secundario="Já existe OS em aberto")
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "reprovadas")
        self.assertEqual(venda.status_tratamento_id, self.st_consta.id)
        self.assertEqual(item["status_aplicado"], "JÁ CONSTA PEDIDO")
        self.assertIsNone(venda.status_esteira_id)
        self.assertIn("Já existe OS em aberto", venda.observacoes)

    def test_consta_pedido_quando_so_existe_o_nome_curto(self):
        self.st_consta.delete()
        pedido = "202610086964805601"
        venda = self._venda(pedido)
        self._pap(pedido, primario="VENDA_NAO_CONFIRMADA", secundario="Já existe OS em aberto")
        sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        self.assertEqual(venda.status_tratamento_id, self.st_consta_curto.id)

    def test_motivo_sem_status_equivalente_nao_altera(self):
        pedido = "202610086964805602"
        venda = self._venda(pedido)
        self._pap(pedido, primario="VENDA_NAO_CONFIRMADA", secundario="Motivo inexistente xyz")
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "inalteradas")
        self.assertIn("não corresponde", item["detalhe"])
        self.assertEqual(venda.status_tratamento_id, self.st_sem.id)

    def test_analise_bo_com_pedido_na_esteira_vira_duplicidade(self):
        self._venda(
            "202610086964805611",
            status=self.st_cad,
            esteira=self.st_agendado,
            os_inst="11223344",
        )
        pedido = "202610086964805603"
        venda = self._venda(pedido)
        self._pap(pedido, primario="ANALISE_BO")
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "reprovadas")
        self.assertEqual(venda.status_tratamento_id, self.st_dup.id)
        self.assertIn("11223344", item["detalhe"])

    def test_analise_bo_sem_pedido_na_esteira_nao_altera(self):
        self._venda("202610086964805612", os_inst="55667788")
        pedido = "202610086964805604"
        venda = self._venda(pedido)
        self._pap(pedido, primario="ANALISE_BO")
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "inalteradas")
        self.assertIn("sem outro pedido", item["detalhe"])
        self.assertEqual(venda.status_tratamento_id, self.st_sem.id)

    def test_status_primario_desconhecido_e_pedido_ausente(self):
        pedido = "202610086964805605"
        venda = self._venda(pedido)
        self._pap(pedido, primario="CONTATO_AGENDADO")
        sem_base = self._venda("202610086964805606")
        sem_proto = self._venda(None)
        resultado = sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        sem_base.refresh_from_db()
        grupo, item = self._por_pedido(resultado, pedido)
        self.assertEqual(grupo, "inalteradas")
        self.assertIn("CONTATO_AGENDADO", item["detalhe"])
        self.assertEqual(venda.status_tratamento_id, self.st_sem.id)
        grupo_ausente, item_ausente = self._por_pedido(resultado, "202610086964805606")
        self.assertEqual(grupo_ausente, "inalteradas")
        self.assertIn("não encontrado", item_ausente["detalhe"])
        self.assertEqual(sem_base.status_tratamento_id, self.st_sem.id)
        self.assertGreaterEqual(resultado["resumo"]["sem_protocolo"], 1)
        self.assertEqual(sem_proto.status_tratamento_id, self.st_sem.id)

    def test_venda_fechada_fora_da_fila_nao_muda(self):
        pedido = "202610086964805607"
        venda = self._venda(pedido, status=self.st_fechado)
        self._pap(
            pedido,
            primario="PEDIDO_GERADO",
            os_inst="08907511",
            data_inst="2026-10-10",
            periodo="Manhã",
        )
        sincronizar_vendas_com_pap(usuario=self.usuario)
        venda.refresh_from_db()
        self.assertEqual(venda.status_tratamento_id, self.st_fechado.id)
        self.assertIsNone(venda.status_esteira_id)

    def test_api_retorna_modal_e_nega_vendedor(self):
        pedido = "202610086964805608"
        self._venda(pedido)
        self._pap(
            pedido,
            primario="PEDIDO_GERADO",
            os_inst="08907512",
            data_inst="2026-10-11",
            periodo="Tarde",
        )
        self.client.force_authenticate(self.vendedor)
        negado = self.client.post("/api/crm/auditoria/sincronizar-vendas-pap/")
        self.assertEqual(negado.status_code, 403)

        self.client.force_authenticate(self.usuario)
        resp = self.client.post("/api/crm/auditoria/sincronizar-vendas-pap/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["resumo"]["esteira"], 1)
        self.assertEqual(resp.data["esteira"][0]["pedido"], pedido)
        self.assertIn("CADASTRADA", resp.data["esteira"][0]["detalhe"])

    def test_busca_pap_atualiza_payload_de_protocolo_conhecido(self):
        HistoricoPapPedido.objects.create(
            numero_pedido="202610086964805609",
            status="ANALISE_BO",
            payload={"numeroPedido": "202610086964805609", "chaveStatusPrimario": "ANALISE_BO"},
        )
        ok = _atualizar_payload_existente(
            "202610086964805609",
            "VENDA",
            "1",
            {
                "numeroPedido": "202610086964805609",
                "chaveStatusPrimario": "PEDIDO_GERADO",
                "produtos": {"bandaLarga": {"osInstalacao": "08907513"}},
            },
        )
        hp = HistoricoPapPedido.objects.get(numero_pedido="202610086964805609")
        self.assertTrue(ok)
        self.assertEqual(hp.status, "PEDIDO_GERADO")
        self.assertEqual(hp.payload["produtos"]["bandaLarga"]["osInstalacao"], "08907513")

    def test_resolver_prefere_ja_consta_pedido(self):
        status, motivo = resolver_status_reprova(
            "Já existe OS em aberto",
            [self.st_sem, self.st_consta, self.st_consta_curto, self.st_cad],
        )
        self.assertEqual(motivo, "")
        self.assertEqual(status.id, self.st_consta.id)


class ResolverIsoladoTests(TestCase):
    def test_nao_usa_status_de_sucesso_como_reprova(self):
        cadastrada = StatusCRM(nome="CADASTRADA", tipo="Tratamento")
        status, motivo = resolver_status_reprova("CADASTRADA", [cadastrada])
        self.assertIsNone(status)
        self.assertIn("não corresponde", motivo)
