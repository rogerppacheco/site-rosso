# crm_app/funil_venda_wpp_service.py
"""
Registro do funil de vendas WhatsApp (fluxo VENDER). Controlado por FUNIL_VENDAS_REGISTRAR.
Não deve lançar exceção para o webhook — falhas só em log.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_CHAVE_FUNIL_ID = "funil_wpp_tentativa_id"

_RANK_FUNIL = {
    "viabilidade": 1,
    "cadastro": 2,
    "contato": 3,
    "credito": 4,
    "oferta": 5,
    "pedido": 6,
}


def _registrar_ativo() -> bool:
    return bool(getattr(settings, "FUNIL_VENDAS_REGISTRAR", False))


def _import_models():
    from crm_app.models import FunilVendaWppEvento, FunilVendaWppTentativa

    return FunilVendaWppTentativa, FunilVendaWppEvento


def etapa_para_funil_estagio(etapa_codigo: str) -> str:
    """Mapeia etapa técnica venda_* para estágio de negócio do funil."""
    from crm_app.models import FunilVendaWppTentativa as T

    e = (etapa_codigo or "").strip()
    if e in (
        "venda_confirmar_matricula",
        "venda_aguardando_pap",
        "venda_cep",
        "venda_numero",
        "venda_referencia",
        "venda_selecionar_endereco",
        "venda_selecionar_complemento",
        "venda_posse_consultar_outro",
        "venda_indisponivel_voltar",
        "venda_erro_retry",
    ):
        return T.FUNIL_VIABILIDADE
    if e in ("venda_cpf", "venda_corrigir_cpf"):
        return T.FUNIL_CADASTRO
    if e in (
        "venda_celular",
        "venda_celular_sec",
        "venda_email",
        "venda_corrigir_celular",
        "venda_corrigir_email",
    ):
        return T.FUNIL_CONTATO
    if e in (
        "venda_forma_pagamento",
        "venda_debito_banco",
        "venda_debito_agencia",
        "venda_debito_conta",
        "venda_debito_digito",
        "venda_plano",
        "venda_fixo",
        "venda_fixo_portabilidade",
        "venda_fixo_portabilidade_numero",
        "venda_fixo_portabilidade_operadora",
        "venda_streaming",
        "venda_streaming_opcoes",
        "venda_confirmar",
        "venda_aguardando_confirmacao",
    ):
        return T.FUNIL_OFERTA
    if e in (
        "venda_aguardando_biometria",
        "venda_aguardando_abrir_os",
        "venda_agendamento_dia",
        "venda_agendamento_confirmar_data",
        "venda_agendamento_periodo",
        "venda_agendamento_confirmar_turno",
        "venda_agendamento_sim_agendar",
        "venda_agendamento_final",
    ):
        return T.FUNIL_PEDIDO
    return T.FUNIL_VIABILIDADE


def _atualizar_max_funil(tentativa, estagio: str) -> None:
    atual = (tentativa.funil_estagio_max or "").strip()
    novo = (estagio or "").strip()
    if not novo:
        return
    r_atual = _RANK_FUNIL.get(atual, 0)
    r_novo = _RANK_FUNIL.get(novo, 0)
    if r_novo > r_atual:
        tentativa.funil_estagio_max = novo


def _append_event(
    tentativa_id: int,
    etapa_codigo: str,
    funil_estagio: str,
    tipo_evento: str,
    payload: Dict[str, Any],
) -> None:
    FunilVendaWppTentativa, FunilVendaWppEvento = _import_models()
    try:
        tentativa = FunilVendaWppTentativa.objects.get(pk=tentativa_id)
    except FunilVendaWppTentativa.DoesNotExist:
        return
    FunilVendaWppEvento.objects.create(
        tentativa=tentativa,
        etapa_codigo=etapa_codigo[:80],
        funil_estagio=funil_estagio,
        tipo_evento=tipo_evento,
        payload=payload or {},
    )
    tentativa.etapa_codigo_atual = etapa_codigo[:80]
    _atualizar_max_funil(tentativa, funil_estagio)
    tentativa.save(update_fields=["etapa_codigo_atual", "funil_estagio_max", "atualizado_em"])


def funil_iniciar_com_cep(sessao, dados: dict, cep_limpo: str) -> None:
    """Chamado ao aceitar CEP válido (primeiro registro da jornada)."""
    if not _registrar_ativo():
        return
    try:
        FunilVendaWppTentativa, FunilVendaWppEvento = _import_models()
        from usuarios.models import Usuario

        tid = (dados or {}).get(_CHAVE_FUNIL_ID)
        if tid:
            return

        uid = (dados or {}).get("usuario_id") or (dados or {}).get("vendedor_id")
        usuario = None
        if uid:
            usuario = Usuario.objects.filter(pk=uid).first()

        bo_id = (dados or {}).get("bo_usuario_id")
        mat = (dados or {}).get("matricula_pap") or ""

        t = FunilVendaWppTentativa.objects.create(
            telefone=sessao.telefone,
            usuario=usuario,
            matricula_pap_snapshot=str(mat)[:80],
            bo_usuario_id=int(bo_id) if bo_id else None,
            sessao_whatsapp=sessao,
            etapa_codigo_atual="venda_cep",
            funil_estagio_max=FunilVendaWppTentativa.FUNIL_VIABILIDADE,
            dados_agregados={"cep": cep_limpo},
        )
        dados[_CHAVE_FUNIL_ID] = t.id
        sessao.dados_temp = dados
        sessao.save(update_fields=["dados_temp"])

        FunilVendaWppEvento.objects.create(
            tentativa=t,
            etapa_codigo="venda_cep",
            funil_estagio=FunilVendaWppTentativa.FUNIL_VIABILIDADE,
            tipo_evento=FunilVendaWppEvento.TIPO_INPUT,
            payload={"cep": cep_limpo},
        )
    except Exception as e:
        logger.exception("[FUNIL WPP] funil_iniciar_com_cep: %s", e)


def funil_registrar_evento_sessao(
    sessao,
    etapa_codigo: str,
    payload: Optional[Dict[str, Any]] = None,
    tipo_evento: Optional[str] = None,
) -> None:
    """Registra um evento se existir tentativa ativa em dados_temp."""
    if not _registrar_ativo():
        return
    try:
        dados = sessao.dados_temp or {}
        tid = dados.get(_CHAVE_FUNIL_ID)
        if not tid:
            return
        FunilVendaWppTentativa, FunilVendaWppEvento = _import_models()
        est = etapa_para_funil_estagio(etapa_codigo)
        te = tipo_evento or FunilVendaWppEvento.TIPO_INPUT
        _append_event(int(tid), etapa_codigo, est, te, payload or {})
        t = FunilVendaWppTentativa.objects.filter(pk=tid).first()
        if t and payload:
            agg = dict(t.dados_agregados or {})
            for k, v in payload.items():
                if k not in ("senha", "senha_pap"):
                    agg[k] = v
            t.dados_agregados = agg
            t.save(update_fields=["dados_agregados", "atualizado_em"])
    except Exception as e:
        logger.exception("[FUNIL WPP] funil_registrar_evento_sessao: %s", e)


def funil_registrar_credito(sessao, resultado_credito: str) -> None:
    if not _registrar_ativo():
        return
    try:
        FunilVendaWppTentativa, FunilVendaWppEvento = _import_models()
        dados = sessao.dados_temp or {}
        tid = dados.get(_CHAVE_FUNIL_ID)
        if not tid:
            return
        tentativa = FunilVendaWppTentativa.objects.filter(pk=tid).first()
        if not tentativa:
            return
        tentativa.credito_resultado = (resultado_credito or "")[:255]
        _atualizar_max_funil(tentativa, FunilVendaWppTentativa.FUNIL_CREDITO)
        tentativa.save(update_fields=["credito_resultado", "funil_estagio_max", "atualizado_em"])

        _append_event(
            int(tid),
            "credito_resultado",
            FunilVendaWppTentativa.FUNIL_CREDITO,
            FunilVendaWppEvento.TIPO_CREDITO,
            {"resultado_credito": resultado_credito},
        )
    except Exception as e:
        logger.exception("[FUNIL WPP] funil_registrar_credito: %s", e)


def funil_registrar_protocolo(sessao, protocolo: str) -> None:
    if not _registrar_ativo():
        return
    try:
        FunilVendaWppTentativa, FunilVendaWppEvento = _import_models()
        dados = sessao.dados_temp or {}
        tid = dados.get(_CHAVE_FUNIL_ID)
        if not tid:
            return
        tentativa = FunilVendaWppTentativa.objects.filter(pk=tid).first()
        if not tentativa:
            return
        tentativa.protocolo_pap = (protocolo or "")[:160]
        _atualizar_max_funil(tentativa, FunilVendaWppTentativa.FUNIL_PEDIDO)
        tentativa.save(update_fields=["protocolo_pap", "funil_estagio_max", "atualizado_em"])

        _append_event(
            int(tid),
            "protocolo_pap",
            FunilVendaWppTentativa.FUNIL_PEDIDO,
            FunilVendaWppEvento.TIPO_PROTOCOLO,
            {"protocolo": protocolo},
        )
    except Exception as e:
        logger.exception("[FUNIL WPP] funil_registrar_protocolo: %s", e)


def funil_finalizar(
    sessao,
    status: str,
    mensagem_erro: str = "",
    limpar_id_dados: bool = False,
) -> None:
    """Finaliza tentativa (abandonado, erro, concluido)."""
    if not _registrar_ativo():
        return
    try:
        FunilVendaWppTentativa, FunilVendaWppEvento = _import_models()
        dados = sessao.dados_temp or {}
        tid = dados.get(_CHAVE_FUNIL_ID)
        if not tid:
            return
        tentativa = FunilVendaWppTentativa.objects.filter(pk=tid).first()
        if not tentativa:
            return
        tentativa.status = status
        tentativa.mensagem_erro = (mensagem_erro or "")[:5000]
        tentativa.finalizado_em = timezone.now()
        tentativa.save(update_fields=["status", "mensagem_erro", "finalizado_em", "atualizado_em"])

        FunilVendaWppEvento.objects.create(
            tentativa=tentativa,
            etapa_codigo="finalizacao",
            funil_estagio=tentativa.funil_estagio_max or FunilVendaWppTentativa.FUNIL_VIABILIDADE,
            tipo_evento=FunilVendaWppEvento.TIPO_STATUS,
            payload={"status": status, "mensagem": mensagem_erro},
        )
        if limpar_id_dados and dados.get(_CHAVE_FUNIL_ID):
            del dados[_CHAVE_FUNIL_ID]
            sessao.dados_temp = dados
            sessao.save(update_fields=["dados_temp"])
    except Exception as e:
        logger.exception("[FUNIL WPP] funil_finalizar: %s", e)


def funil_finalizar_abandonado(sessao, motivo: str = "cancelado_ou_reset") -> None:
    T, _ = _import_models()
    funil_finalizar(sessao, T.STATUS_ABANDONADO, motivo, limpar_id_dados=True)


def funil_finalizar_erro(sessao, msg: str) -> None:
    T, _ = _import_models()
    funil_finalizar(sessao, T.STATUS_ERRO, msg, limpar_id_dados=True)


def funil_finalizar_concluido(sessao) -> None:
    T, _ = _import_models()
    funil_finalizar(sessao, T.STATUS_CONCLUIDO, "", limpar_id_dados=True)
