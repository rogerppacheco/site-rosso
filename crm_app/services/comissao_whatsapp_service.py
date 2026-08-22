"""
Serviço de envio de resumo de comissão por WhatsApp (card/imagem).

Centraliza o cálculo simplificado por consultor (comissão bruta, descontos por venda)
e a montagem do payload do card enviado via Z-API, para que a view apenas valide
a entrada e acione o envio.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from django.contrib.auth import get_user_model
from crm_app.models import RegraComissao, Venda

from .comissionamento_service import (
    _encontrar_regra_comissao,
    _obter_intervalo_mes,
    _tipo_cliente_e_canal,
)

logger = logging.getLogger(__name__)


def _calcular_resumo_card_consultor(
    ano: int,
    mes: int,
    consultor: Any,
    todas_regras: list[RegraComissao],
) -> dict[str, Any]:
    """
    Calcula o resumo de comissão do consultor no mês para montagem do card WhatsApp.

    Usa as mesmas regras de regra por plano/tipo_cliente/canal e meta acelerada;
    considera apenas descontos por venda (boleto, inclusão, antecipação, adiant. CNPJ),
    sem lançamentos financeiros nem bônus de campanha, para manter o card enxuto.
    """
    data_inicio, data_fim = _obter_intervalo_mes(ano, mes)

    vendas = Venda.objects.filter(
        vendedor=consultor,
        ativo=True,
        status_esteira__nome__iexact="INSTALADA",
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).select_related("plano", "forma_pagamento", "cliente")

    qtd_instaladas = vendas.count()
    meta = consultor.meta_comissao or 0
    bateu_meta = qtd_instaladas >= meta

    stats_planos: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"qtd": 0, "valor_unit": 0.0, "total": 0.0}
    )
    stats_descontos: dict[str, float] = defaultdict(float)
    comissao_bruta = 0.0

    for v in vendas:
        tipo_cliente, canal_vendedor = _tipo_cliente_e_canal(v, consultor)
        regra = _encontrar_regra_comissao(
            todas_regras, v, consultor, tipo_cliente, canal_vendedor
        )
        valor_item = (
            float(regra.valor_acelerado if bateu_meta else regra.valor_base)
            if regra
            else 0.0
        )
        comissao_bruta += valor_item

        nm_plano = v.plano.nome
        stats_planos[nm_plano]["qtd"] += 1
        stats_planos[nm_plano]["total"] += valor_item

        doc = v.cliente.cpf_cnpj if v.cliente else ""
        doc_limpo = "".join(filter(str.isdigit, doc))

        from crm_app.services.cnpj_mei_service import (
            elegivel_adiantamento_cnpj,
            elegivel_desconto_boleto_folha,
        )

        if elegivel_desconto_boleto_folha(v):
            val = float(consultor.desconto_boleto or 0)
            if val > 0:
                stats_descontos["Boleto"] += val
        if v.inclusao:
            val = float(consultor.desconto_inclusao_viabilidade or 0)
            if val > 0:
                stats_descontos["Inclusão"] += val
        if v.antecipou_instalacao:
            val = float(consultor.desconto_instalacao_antecipada or 0)
            if val > 0:
                stats_descontos["Antecipação"] += val
        if elegivel_adiantamento_cnpj(v):
            val = float(consultor.adiantamento_cnpj or 0)
            if val > 0:
                stats_descontos["Adiant. CNPJ"] += val

    total_descontos = sum(stats_descontos.values())
    liquido = comissao_bruta - total_descontos

    detalhes_planos = [
        {
            "nome": p_nome,
            "qtd": dados["qtd"],
            "valor": f"R$ {dados['total']:.2f}".replace(".", ","),
        }
        for p_nome, dados in stats_planos.items()
    ]
    detalhes_descontos = [
        {"motivo": motivo, "valor": f"-R$ {val:.2f}".replace(".", ",")}
        for motivo, val in stats_descontos.items()
    ]

    return {
        "titulo": "Resumo Comissionamento",
        "vendedor": consultor.username.upper(),
        "periodo": f"{mes}/{ano}",
        "total": f"R$ {liquido:.2f}".replace(".", ","),
        "detalhes_planos": detalhes_planos,
        "detalhes_descontos": detalhes_descontos,
    }


def enviar_comissao_whatsapp_consultores(
    ano: int,
    mes: int,
    consultores_ids: list[int],
) -> tuple[int, list[str]]:
    """
    Envia o card de resumo de comissão por WhatsApp para cada consultor informado.

    Para cada ID: busca o usuário, valida telefone, calcula o resumo do mês (mesmas
    regras do relatório de comissionamento, versão simplificada para o card) e chama
    o WhatsAppService. Falhas de envio ou de consultor sem WhatsApp são acumuladas
    em erros sem interromper os demais.

    Args:
        ano: Ano de referência.
        mes: Mês de referência (1-12).
        consultores_ids: Lista de PKs de usuários (consultores) para envio.

    Returns:
        Tupla (quantidade de envios com sucesso, lista de mensagens de erro).
    """
    User = get_user_model()
    todas_regras = list(
        RegraComissao.objects.select_related("plano", "consultor").all()
    )

    from crm_app.whatsapp_service import WhatsAppService

    svc = WhatsAppService()
    sucessos = 0
    erros: list[str] = []

    for c_id in consultores_ids:
        try:
            consultor = User.objects.get(id=c_id)
            telefone = consultor.tel_whatsapp
            if not telefone:
                erros.append(f"{consultor.username}: Sem WhatsApp cadastrado.")
                continue

            dados_img = _calcular_resumo_card_consultor(
                ano, mes, consultor, todas_regras
            )
            if svc.enviar_resumo_comissao(telefone, dados_img):
                sucessos += 1
            else:
                erros.append(f"{consultor.username}: Falha no envio (Z-API).")
        except User.DoesNotExist:
            erros.append(f"ID {c_id}: Consultor não encontrado.")
        except Exception as e:
            logger.exception("Erro ao processar envio para %s: %s", c_id, e)
            erros.append(f"ID {c_id}: Erro interno.")

    return sucessos, erros
