"""
Serviço de comissionamento: geração do relatório de comissões por consultor e período.

Centraliza as regras de negócio de:
- Cálculo de comissão bruta por venda (regras por plano, tipo de cliente e canal).
- Descontos previstos (boleto, inclusão/viabilidade, antecipação, adiantamento CNPJ).
- Lançamentos financeiros já processados.
- Bônus de campanhas (meta de vendas e prêmios).
- Histórico de fechamentos dos últimos meses.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum

from crm_app.views import _filtro_data_efetiva_instalacao_intervalo_venda
from crm_app.models import (
    Campanha,
    CicloPagamento,
    LancamentoFinanceiro,
    PagamentoComissao,
    RegraComissao,
    Venda,
)


def _obter_intervalo_mes(ano: int, mes: int) -> tuple[datetime, datetime]:
    """Retorna (data_inicio, data_fim) do mês para filtros de período."""
    data_inicio = datetime(ano, mes, 1)
    if mes == 12:
        data_fim = datetime(ano + 1, 1, 1)
    else:
        data_fim = datetime(ano, mes + 1, 1)
    return data_inicio, data_fim


def _tipo_cliente_e_canal(venda: Venda, consultor: Any) -> tuple[str, str]:
    """Deriva tipo_cliente (CPF/CNPJ para tabela) e canal do vendedor."""
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

    tipo_cliente = tipo_cliente_comissao(venda)
    canal_vendedor = getattr(consultor, "canal", "PAP") or "PAP"
    return tipo_cliente, canal_vendedor


def _encontrar_regra_comissao(
    todas_regras: list[RegraComissao],
    venda: Venda,
    consultor: Any,
    tipo_cliente: str,
    canal_vendedor: str,
) -> RegraComissao | None:
    """Busca a regra de comissão aplicável: primeiro por consultor, depois genérica (consultor=None)."""
    regra = next(
        (
            r
            for r in todas_regras
            if r.plano_id == venda.plano_id
            and r.tipo_cliente == tipo_cliente
            and r.tipo_venda == canal_vendedor
            and r.consultor_id == consultor.id
        ),
        None,
    )
    if not regra:
        regra = next(
            (
                r
                for r in todas_regras
                if r.plano_id == venda.plano_id
                and r.tipo_cliente == tipo_cliente
                and r.tipo_venda == canal_vendedor
                and r.consultor is None
            ),
            None,
        )
    return regra


def _tipo_lancamento_display(tipo: str) -> str:
    """Mapeia tipo interno de lançamento para rótulo de exibição no relatório."""
    if tipo == "ADIANTAMENTO_CNPJ":
        return "Adiant. CNPJ"
    if tipo == "ADIANTAMENTO_COMISSAO":
        return "Adiantamento"
    if tipo == "BONUS_PREMIACAO":
        return "Bônus/Premiação"
    if tipo == "DESCONTO":
        return "Desconto"
    return "Outro"


def gerar_relatorio_comissionamento(ano: int, mes: int) -> dict[str, Any]:
    """
    Gera o relatório completo de comissionamento para um mês/ano.

    Para cada consultor ativo calcula:
    - Vendas instaladas no período e comissão bruta (regras por plano/tipo/cliente/canal).
    - Descontos previstos (boleto, inclusão, antecipação, adiant. CNPJ) e fixos (INSS).
    - Lançamentos financeiros já processados no mês.
    - Bônus de campanhas cujo prazo cobre o mês e cuja meta foi atingida.
    - Totais (líquido) e detalhes por plano, descontos e bônus.

    Também monta o histórico dos últimos 6 meses (totais de ciclo e fechamento).

    Regras de negócio:
    - Comissão acelerada só se qtd_instaladas >= meta_comissao do consultor.
    - Descontos previstos só entram se a venda ainda não tiver a flag de processado.
    - Campanhas usam data_fim no mês, filtros por plano, forma de pagamento e canal.

    Args:
        ano: Ano de referência (ex.: 2025).
        mes: Mês de referência (1-12).

    Returns:
        Dicionário com chaves:
        - periodo: str no formato "M/AAAA"
        - relatorio_consultores: lista de dicts por consultor (detalhes de planos, descontos, bônus).
        - historico_pagamentos: lista de dicts com totais e status dos últimos meses.
    """
    User = get_user_model()
    data_inicio, data_fim = _obter_intervalo_mes(ano, mes)

    consultores = User.objects.filter(is_active=True).order_by("username")
    todas_regras = list(
        RegraComissao.objects.select_related("plano", "consultor").all()
    )

    lancamentos_mes = LancamentoFinanceiro.objects.filter(
        data__gte=data_inicio,
        data__lt=data_fim,
    )
    mapa_lancamentos: dict[int, list[LancamentoFinanceiro]] = defaultdict(list)
    for l in lancamentos_mes:
        mapa_lancamentos[l.usuario_id].append(l)

    campanhas_mes = Campanha.objects.filter(
        ativo=True,
        data_fim__year=ano,
        data_fim__month=mes,
    ).prefetch_related("planos_elegiveis", "formas_pagamento_elegiveis")

    relatorio: list[dict[str, Any]] = []

    for consultor in consultores:
        di = data_inicio.date()
        df = (data_fim - timedelta(days=1)).date()

        vendas = (
            Venda.objects.filter(
                vendedor=consultor,
                ativo=True,
                status_esteira__nome__iexact="INSTALADA",
            )
            .filter(_filtro_data_efetiva_instalacao_intervalo_venda(di, df))
            .select_related("plano", "forma_pagamento", "cliente")
        )

        qtd_instaladas = vendas.count()
        meta = consultor.meta_comissao or 0
        atingimento = (qtd_instaladas / meta * 100) if meta > 0 else 0
        bateu_meta = qtd_instaladas >= meta

        comissao_bruta = 0.0
        stats_planos: dict[tuple[str, float], dict[str, Any]] = defaultdict(
            lambda: {"qtd": 0, "total": 0.0}
        )
        stats_descontos: dict[str, float] = defaultdict(float)
        stats_bonus: dict[str, float] = defaultdict(float)

        for v in vendas:
            tipo_cliente, canal_vendedor = _tipo_cliente_e_canal(v, consultor)
            regra = _encontrar_regra_comissao(
                todas_regras, v, consultor, tipo_cliente, canal_vendedor
            )
            valor_item = (
                float(
                    regra.valor_acelerado if bateu_meta else regra.valor_base
                )
                if regra
                else 0.0
            )
            comissao_bruta += valor_item

            key_plano = (v.plano.nome, valor_item)
            stats_planos[key_plano]["qtd"] += 1
            stats_planos[key_plano]["total"] += valor_item

            doc = v.cliente.cpf_cnpj if v.cliente else ""
            doc_limpo = "".join(filter(str.isdigit, doc))

            from crm_app.services.cnpj_mei_service import (
                elegivel_adiantamento_cnpj,
                elegivel_desconto_boleto_folha,
            )

            if elegivel_desconto_boleto_folha(v):
                if not v.flag_desc_boleto:
                    val = float(consultor.desconto_boleto or 0)
                    if val > 0:
                        stats_descontos["Desc. Boleto (Previsto)"] += val

            if v.inclusao:
                if not v.flag_desc_viabilidade:
                    val = float(consultor.desconto_inclusao_viabilidade or 0)
                    if val > 0:
                        stats_descontos["Desc. Inclusão (Previsto)"] += val

            if v.antecipou_instalacao:
                if not v.flag_desc_antecipacao:
                    val = float(consultor.desconto_instalacao_antecipada or 0)
                    if val > 0:
                        stats_descontos["Desc. Antecipação (Previsto)"] += val

            if elegivel_adiantamento_cnpj(v):
                if not v.flag_adiant_cnpj:
                    val = float(consultor.adiantamento_cnpj or 0)
                    if val > 0:
                        stats_descontos["Adiant. CNPJ (Previsto)"] += val

        if consultor.desconto_inss_fixo and float(consultor.desconto_inss_fixo) > 0:
            stats_descontos["INSS / Encargos (Fixo)"] += float(
                consultor.desconto_inss_fixo
            )

        for l in mapa_lancamentos.get(consultor.id, []):
            if l.tipo == "BONUS_PREMIACAO":
                tipo_display = _tipo_lancamento_display(l.tipo)
                descricao_item = l.descricao or ""
                chave_exibicao = (
                    f"{tipo_display}: {descricao_item}"
                    if descricao_item
                    else tipo_display
                )
                stats_bonus[chave_exibicao] += float(l.valor)
                continue
            tipo_display = _tipo_lancamento_display(l.tipo)
            descricao_item = l.descricao or ""
            chave_exibicao = (
                f"{tipo_display}: {descricao_item}" if descricao_item else tipo_display
            )
            stats_descontos[chave_exibicao] += float(l.valor)

        for camp in campanhas_mes:
            q_camp = Q(vendedor=consultor, ativo=True)
            q_camp &= Q(
                data_criacao__date__gte=camp.data_inicio,
                data_criacao__date__lte=camp.data_fim,
            )
            if camp.tipo_meta == "LIQUIDA":
                q_camp &= Q(status_esteira__nome__iexact="INSTALADA")
            if camp.canal_alvo != "TODOS":
                q_camp &= Q(vendedor__canal=camp.canal_alvo)
            planos_ids = [p.id for p in camp.planos_elegiveis.all()]
            if planos_ids:
                q_camp &= Q(plano_id__in=planos_ids)
            pgto_ids = [fp.id for fp in camp.formas_pagamento_elegiveis.all()]
            if pgto_ids:
                q_camp &= Q(forma_pagamento_id__in=pgto_ids)
            total_atingido = Venda.objects.filter(q_camp).count()
            if total_atingido >= camp.meta_vendas:
                stats_bonus[f"Prêmio: {camp.nome}"] += float(camp.valor_premio)

        total_descontos = sum(stats_descontos.values())
        total_bonus = sum(stats_bonus.values())
        valor_liquido = (comissao_bruta + total_bonus) - total_descontos

        lista_planos_detalhe = [
            {
                "plano": nome_plano,
                "unitario": unitario,
                "qtd": dados["qtd"],
                "total": dados["total"],
            }
            for (nome_plano, unitario), dados in stats_planos.items()
        ]
        lista_planos_detalhe.sort(key=lambda x: x["total"], reverse=True)

        lista_descontos_detalhe = [
            {"motivo": k, "valor": v} for k, v in stats_descontos.items()
        ]
        lista_descontos_detalhe.sort(key=lambda x: x["valor"], reverse=True)

        lista_bonus_detalhe = [
            {"motivo": k, "valor": v} for k, v in stats_bonus.items()
        ]
        lista_bonus_detalhe.sort(key=lambda x: x["valor"], reverse=True)

        relatorio.append(
            {
                "consultor_id": consultor.id,
                "consultor_nome": consultor.username.upper(),
                "qtd_instaladas": qtd_instaladas,
                "meta": meta,
                "atingimento_pct": round(atingimento, 1),
                "comissao_bruta": comissao_bruta,
                "total_descontos": total_descontos,
                "total_bonus": total_bonus,
                "valor_liquido": valor_liquido,
                "detalhes_planos": lista_planos_detalhe,
                "detalhes_descontos": lista_descontos_detalhe,
                "detalhes_bonus": lista_bonus_detalhe,
            }
        )

    total_ciclo = (
        CicloPagamento.objects.filter(
            ano=ano,
            mes=str(mes),
        ).aggregate(Sum("valor_comissao_final"))["valor_comissao_final__sum"]
        or 0
    )

    fechamento = PagamentoComissao.objects.filter(
        referencia_ano=ano,
        referencia_mes=mes,
    ).first()

    total_pago = fechamento.total_pago_consultores if fechamento else 0.0

    historico: list[dict[str, Any]] = [
        {
            "ano_mes": f"{mes}/{ano}",
            "total_pago_equipe": total_pago,
            "total_recebido_ciclo": total_ciclo,
            "diferenca_pago_recebido": float(total_ciclo) - float(total_pago),
            "status": "Fechado" if fechamento else "Aberto",
        }
    ]

    return {
        "periodo": f"{mes}/{ano}",
        "relatorio_consultores": relatorio,
        "historico_pagamentos": historico,
    }
