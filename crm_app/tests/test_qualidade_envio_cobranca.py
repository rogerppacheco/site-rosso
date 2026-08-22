"""Testes das filas de atraso FPD e do teto do job de cobrança."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from django.test import SimpleTestCase

from crm_app.services.fpd_import_service import extrair_campos_linha_fpd
from crm_app.services.qualidade_service import (
    ATRASO_LIMITE_FPD_DIAS,
    FILA_ATRASADOS_GTE60,
    FILA_ATRASADOS_LT60,
    HORARIO_JOB_COBRANCA,
    _id_contrato_fpd,
    classificar_fila_atraso,
    classificar_motivo_bloqueio_cobranca,
    corte_vencimento_fpd,
    escolher_template_fatura_cobranca,
    extrair_data_promessa_texto,
    proximos_no_job_cobranca,
    validar_fatura_para_envio_cobranca,
)
from crm_app.services.whatsapp.nio_templates import (
    BTN_INFORMAR_PREVISAO,
    TEMPLATE_FATURA_LEMBRETE_5D,
    TEMPLATE_FATURA_RECORRENTE,
    TEMPLATE_FATURA_REDUCAO_SINAL,
    TEMPLATE_FATURA_VENCIDA_5D,
    classificar_botao,
)


class TestValidarFaturaCobranca(SimpleTestCase):
    def test_bloqueia_valor_zero(self) -> None:
        fatura = SimpleNamespace(valor=0, data_vencimento=date(2026, 6, 30))
        ok, msg = validar_fatura_para_envio_cobranca(fatura)
        self.assertFalse(ok)
        self.assertIn("valor", msg.lower())

    def test_bloqueia_sem_vencimento(self) -> None:
        fatura = SimpleNamespace(valor=99.9, data_vencimento=None)
        ok, msg = validar_fatura_para_envio_cobranca(fatura)
        self.assertFalse(ok)
        self.assertIn("vencimento", msg.lower())

    def test_permite_valor_e_vencimento(self) -> None:
        fatura = SimpleNamespace(valor="120.50", data_vencimento=date(2026, 6, 30))
        ok, msg = validar_fatura_para_envio_cobranca(fatura)
        self.assertTrue(ok)
        self.assertEqual(msg, "")


class TestFilasAtrasoFpd(SimpleTestCase):
    def test_corte_60_dias(self) -> None:
        hoje = date(2026, 8, 14)
        self.assertEqual(corte_vencimento_fpd(hoje), date(2026, 6, 15))
        self.assertEqual(ATRASO_LIMITE_FPD_DIAS, 60)

    def test_59_dias_ainda_recuperavel(self) -> None:
        self.assertEqual(classificar_fila_atraso(59), FILA_ATRASADOS_LT60)

    def test_60_dias_fpd_consolidado(self) -> None:
        self.assertEqual(classificar_fila_atraso(60), FILA_ATRASADOS_GTE60)

    def test_acima_de_60(self) -> None:
        self.assertEqual(classificar_fila_atraso(74), FILA_ATRASADOS_GTE60)


class TestLimiteJobCobranca(SimpleTestCase):
    def test_sem_teto_envia_todos(self) -> None:
        self.assertEqual(proximos_no_job_cobranca(831, 0), 831)

    def test_com_teto_respeita_limite(self) -> None:
        self.assertEqual(proximos_no_job_cobranca(831, 80), 80)

    def test_faltam_zero(self) -> None:
        self.assertEqual(proximos_no_job_cobranca(0, 0), 0)
        self.assertEqual(proximos_no_job_cobranca(0, 80), 0)


class TestIdContratoFpd(SimpleTestCase):
    def test_usa_numero_definitivo(self) -> None:
        contrato = SimpleNamespace(numero_contrato_definitivo=' 123456789 ')
        fatura = SimpleNamespace(id_contrato_fpd='999')
        self.assertEqual(_id_contrato_fpd(contrato, fatura), '123456789')

    def test_fallback_fatura(self) -> None:
        contrato = SimpleNamespace(numero_contrato_definitivo='')
        fatura = SimpleNamespace(id_contrato_fpd=' 987654 ')
        self.assertEqual(_id_contrato_fpd(contrato, fatura), '987654')

    def test_vazio_quando_ausente(self) -> None:
        contrato = SimpleNamespace(numero_contrato_definitivo=None)
        self.assertEqual(_id_contrato_fpd(contrato), '')


class TestExtrairContratoFpd(SimpleTestCase):
    def test_aceita_coluna_contrato(self) -> None:
        campos = extrair_campos_linha_fpd({'contrato': '555111', 'indicador': 'FPD'})
        self.assertEqual(campos['id_contrato'], '555111')

    def test_id_contrato_tem_prioridade(self) -> None:
        campos = extrair_campos_linha_fpd({
            'id_contrato': '111',
            'contrato': '222',
            'indicador': 'FPD',
        })
        self.assertEqual(campos['id_contrato'], '111')


class TestTemplateReducaoSinalQualidade(SimpleTestCase):
    def test_tela_qualidade_sempre_reducao_sinal(self) -> None:
        fatura = SimpleNamespace(data_vencimento=date(2026, 8, 10))
        tpl, incluir = escolher_template_fatura_cobranca(
            fatura, modo='reducao_sinal', hoje=date(2026, 8, 18)
        )
        self.assertEqual(tpl, TEMPLATE_FATURA_REDUCAO_SINAL)
        self.assertFalse(incluir)

    def test_job_d5_antes_continua_lembrete(self) -> None:
        fatura = SimpleNamespace(data_vencimento=date(2026, 8, 23))
        tpl, incluir = escolher_template_fatura_cobranca(
            fatura, modo='template', hoje=date(2026, 8, 18)
        )
        self.assertEqual(tpl, TEMPLATE_FATURA_LEMBRETE_5D)
        self.assertFalse(incluir)

    def test_job_vencida_ate_7_dias(self) -> None:
        fatura = SimpleNamespace(data_vencimento=date(2026, 8, 13))
        tpl, _ = escolher_template_fatura_cobranca(
            fatura, modo='template', hoje=date(2026, 8, 18)
        )
        self.assertEqual(tpl, TEMPLATE_FATURA_VENCIDA_5D)

    def test_job_recorrente_apos_7_dias(self) -> None:
        fatura = SimpleNamespace(data_vencimento=date(2026, 8, 1))
        tpl, incluir = escolher_template_fatura_cobranca(
            fatura, modo='template', hoje=date(2026, 8, 18)
        )
        self.assertEqual(tpl, TEMPLATE_FATURA_RECORRENTE)
        self.assertTrue(incluir)

    def test_botao_informar_previsao(self) -> None:
        self.assertEqual(classificar_botao('Informar previsão'), BTN_INFORMAR_PREVISAO)
        self.assertEqual(classificar_botao('INFORMAR PREVISAO'), BTN_INFORMAR_PREVISAO)

    def test_extrai_data_completa(self) -> None:
        self.assertEqual(
            extrair_data_promessa_texto('25/08/2026', hoje=date(2026, 8, 18)),
            date(2026, 8, 25),
        )

    def test_extrai_data_sem_ano_no_futuro(self) -> None:
        self.assertEqual(
            extrair_data_promessa_texto('25/08', hoje=date(2026, 8, 18)),
            date(2026, 8, 25),
        )

    def test_rejeita_data_passada(self) -> None:
        self.assertIsNone(
            extrair_data_promessa_texto('10/08/2026', hoje=date(2026, 8, 18))
        )

    def test_rejeita_texto_que_nao_e_so_data(self) -> None:
        self.assertIsNone(
            extrair_data_promessa_texto('pago dia 25/08/2026', hoje=date(2026, 8, 18))
        )


class TestMotivoBloqueioCobranca(SimpleTestCase):
    def test_orfao_sem_cpf(self) -> None:
        self.assertEqual(
            classificar_motivo_bloqueio_cobranca(False, ''),
            'Órfão / sem CPF',
        )

    def test_sem_vencimento(self) -> None:
        self.assertEqual(
            classificar_motivo_bloqueio_cobranca(
                True, 'Fatura sem data de vencimento. Atualize a fatura.'
            ),
            'Sem data de vencimento',
        )

    def test_valor_zerado(self) -> None:
        self.assertEqual(
            classificar_motivo_bloqueio_cobranca(
                True, 'Fatura sem valor válido (R$ 0,00 ou vazio).'
            ),
            'Valor zerado ou vazio',
        )

    def test_job_agora_as_nove(self) -> None:
        self.assertEqual(HORARIO_JOB_COBRANCA, '09:00')
