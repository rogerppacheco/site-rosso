"""Testes do cruzamento PAP × OSAB (montar legado, sem gravar venda)."""
from django.test import SimpleTestCase

import pandas as pd

from crm_app.legado_pap_osab import (
    cruzar_pap_osab,
    map_status_esteira,
    montar_xlsx,
    os_variants,
    plano_por_velocidade,
)


def _pap_row(**kwargs):
    base = {
        "Pedido": "202607011232833369",
        "OS instalação": "0174568",
        "Status": "Pedido Gerado",
        "Matrícula vendedor": "TT833370",
        "Vendedor": "LUCINEIA MATIAS DOS SANTOS",
        "Cliente": "VANILDA MARQUES VIANA",
        "CPF": "026.746.576-93",
        "Data do pedido": "2026-07-01 18:29:00",
        "Data de nascimento": "1969-12-29",
        "Nome da mãe": "MARIA GERALDA",
        "E-mail": "maria@email.com",
        "Celular principal": "(31) 98275-5703",
        "CEP": "35703-098",
        "Logradouro": "Rua Abel",
        "Número": "37",
        "Bairro": "Centro",
        "Cidade": "Sete Lagoas",
        "UF": "MG",
        "Ponto de referência": "Casa A",
        "Plano": "Nio Fibra Essencial",
        "Velocidade": "500 Mega",
        "Forma de pagamento": "Boleto",
        "Período instalação": "Noite",
    }
    base.update(kwargs)
    return base


def _osab_row(**kwargs):
    base = {
        "PEDIDO": "10174568",
        "DESCRICAO": "IGOR CRISTIANO",
        "PDV_SAP": "1069321",
        "SITUACAO": "Concluído",
        "VELOCIDADE": "500MB",
        "CAMPANHA": "BL_500MB_VAR",
        "meio_pagamento": "Boleto Digital",
        "DATA_ABERTURA": "2026-07-01 18:29:00",
        "DATA_FECHAMENTO": "2026-07-06 10:00:00",
        "DATA_AGENDAMENTO": "2026-07-06 00:00:00",
        "LOCALIDADE": "SETE LAGOAS",
        "UF": "MG",
        "MATRICULA_VENDEDOR": "TT833370",
    }
    base.update(kwargs)
    return base


class LegadoPapOsabTest(SimpleTestCase):
    def test_os_variants_completa_digito_1(self):
        vars_ = os_variants("0174568")
        self.assertIn("10174568", vars_)

    def test_plano_1gb_mesh(self):
        self.assertEqual(
            plano_por_velocidade("1GB", "BL_1GB_VAR_MAI26_FIBRAX_MESH_160"),
            "NIO FIBRA ULTRA 1GB",
        )
        self.assertEqual(
            plano_por_velocidade("1GB", "BL_1GB_VAR_AQ_JUL26_75_GP_PL30"),
            "NIO FIBRA ULTRA 1GB (SEM MESH)",
        )

    def test_status_concluido_instalada(self):
        self.assertEqual(map_status_esteira("Concluído", "2026-07-06"), "INSTALADA")
        self.assertEqual(map_status_esteira("Cancelado", None), "CANCELADA")

    def test_cruzamento_nao_grava_e_preenche_modelo(self):
        pap = pd.DataFrame([_pap_row()])
        osab = pd.DataFrame([_osab_row()])
        out = cruzar_pap_osab(
            pap,
            [("JUN", osab)],
            parceiro="IGOR CRISTIANO",
            pdv_sap="1069321",
            somente_instalada=True,
        )
        self.assertFalse(out["resumo"]["grava_venda"])
        self.assertEqual(out["resumo"]["cruzados"], 1)
        self.assertEqual(out["resumo"]["modelo_legado"], 1)
        row = out["modelo"].iloc[0]
        self.assertEqual(row["OS"], "10174568")
        self.assertEqual(row["CPF_CNPJ_CLIENTE"], "02674657693")
        self.assertEqual(row["NOME_CLIENTE"], "VANILDA MARQUES VIANA")
        self.assertEqual(row["STATUS_ESTEIRA"], "INSTALADA")
        self.assertEqual(row["STATUS_TRATAMENTO"], "CADASTRADA")
        self.assertEqual(row["NOME_PLANO"], "NIO FIBRA ESSENCIAL 500MB")
        self.assertEqual(row["FORMA_PAGAMENTO"], "BOLETO")
        self.assertEqual(row["EMAIL_CLIENTE"], "MARIA@EMAIL.COM")
        self.assertEqual(row["LOGIN_VENDEDOR"], "TT833370")

    def test_parceiro_errado_nao_casa(self):
        pap = pd.DataFrame([_pap_row()])
        osab = pd.DataFrame([_osab_row()])
        out = cruzar_pap_osab(pap, [("JUN", osab)], parceiro="ROSSO TELECOM")
        self.assertEqual(out["resumo"]["cruzados"], 0)
        self.assertEqual(len(out["modelo"]), 0)

    def test_cancelada_fica_fora_quando_somente_instalada(self):
        pap = pd.DataFrame([_pap_row()])
        osab = pd.DataFrame([_osab_row(SITUACAO="Cancelado", DATA_FECHAMENTO="")])
        out = cruzar_pap_osab(
            pap, [("AGO", osab)], parceiro="IGOR CRISTIANO", somente_instalada=True
        )
        self.assertEqual(out["resumo"]["cruzados"], 1)
        self.assertEqual(out["resumo"]["modelo_legado"], 0)
        self.assertEqual(out["resumo"]["cancelada"], 1)
        self.assertEqual(len(out["outros"]), 1)

    def test_xlsx_primeira_aba_e_modelo(self):
        pap = pd.DataFrame([_pap_row()])
        osab = pd.DataFrame([_osab_row()])
        out = cruzar_pap_osab(pap, [("JUL", osab)], parceiro="IGOR CRISTIANO")
        blob = montar_xlsx(out)
        sheets = pd.read_excel(blob, sheet_name=None, dtype=str)
        self.assertIn("Modelo Legado", sheets)
        self.assertEqual(list(sheets.keys())[0], "Modelo Legado")
        self.assertEqual(sheets["Modelo Legado"].iloc[0]["OS"], "10174568")
