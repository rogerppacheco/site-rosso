"""
Serviço do Painel do Agente Financeiro (Segunda-feira).
Calcula por usuário ativo, para uma semana seg–sáb:
passagem, almoço, faltas, retirada, total CNPJ, premiação cartão,
adiantamento solicitado, valor avulso (descontos), campanha, total a receber.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Sum, Q

from crm_app.models import Venda, LancamentoFinanceiro, Campanha, FormaPagamento, ComissaoOperadora
from presenca.models import Presenca, DiaNaoUtil
from usuarios.models import Usuario


# Constantes de valores (podem vir de config no futuro)
VALOR_PREMIACAO_CARTAO = Decimal("30.00")


def get_semana_seg_sab(semana_inicio: date) -> tuple[date, date]:
    """semana_inicio = segunda-feira. Retorna (seg, sáb)."""
    if semana_inicio.weekday() != 0:
        # Ajustar para segunda anterior
        semana_inicio = semana_inicio - timedelta(days=semana_inicio.weekday())
    semana_fim = semana_inicio + timedelta(days=5)  # sábado
    return semana_inicio, semana_fim


def get_dias_uteis_semana_seg_sab(inicio: date, fim: date) -> list[date]:
    """Dias úteis no período (seg a sáb), excluindo feriados."""
    feriados = set(
        DiaNaoUtil.objects.filter(data__range=(inicio, fim)).values_list("data", flat=True)
    )
    dias = []
    atual = inicio
    while atual <= fim:
        # 0=seg, 5=sáb (incluímos sábado)
        if atual.weekday() <= 5 and atual not in feriados:
            dias.append(atual)
        atual += timedelta(days=1)
    return dias


def _is_cnpj(cliente) -> bool:
    if not cliente or not getattr(cliente, "cpf_cnpj", None):
        return False
    digits = re.sub(r"\D", "", str(cliente.cpf_cnpj))
    return len(digits) == 14


def _is_cartao_credito(forma_pagamento) -> bool:
    if not forma_pagamento or not getattr(forma_pagamento, "nome", None):
        return False
    nome = (forma_pagamento.nome or "").upper()
    return (
        "CARTÃO" in nome
        or "CARTAO" in nome
        or "CRÉDITO" in nome
        or "CREDITO" in nome
    ) and "DÉBITO" not in nome


def gerar_painel_semana(semana_inicio: date) -> list[dict[str, Any]]:
    """
    Gera a tabela do Painel Segunda para a semana (segunda a sábado).
    semana_inicio: data da segunda-feira (YYYY-MM-DD).
    Retorna lista de dicts, um por usuário ativo.
    """
    seg, sab = get_semana_seg_sab(semana_inicio)
    dias_uteis = get_dias_uteis_semana_seg_sab(seg, sab)
    qtd_dias_semana = len(dias_uteis)

    usuarios = Usuario.objects.filter(is_active=True).order_by("first_name", "username")

    # Presenças na semana (faltas com desconto)
    presencas = Presenca.objects.filter(
        data__range=(seg, sab),
        colaborador__in=usuarios,
    ).select_related("motivo")

    mapa_presencas: dict[int, dict[date, dict]] = {}
    for p in presencas:
        uid = p.colaborador_id
        if uid not in mapa_presencas:
            mapa_presencas[uid] = {}
        gera_desconto = bool(
            p.status is False and p.motivo and getattr(p.motivo, "gera_desconto", False)
        )
        mapa_presencas[uid][p.data] = {"status": p.status, "gera_desconto": gera_desconto}

    # Recebimento Operadora (valor que a empresa recebe por plano) – para coluna "Total de vendas"
    mapa_comissao_op = {}
    for c in ComissaoOperadora.objects.all().select_related("plano"):
        mapa_comissao_op[c.plano_id] = {
            "base": Decimal(str(c.valor_base or 0)),
            "bonus": Decimal(str(c.bonus_transicao or 0)),
            "fim_bonus": c.data_fim_bonus,
        }

    # Vendas instaladas na semana (data efetiva: física se houver, senão OSAB)
    from crm_app.views import _filtro_data_efetiva_instalacao_intervalo_venda

    status_instalada = Q(status_esteira__nome__iexact="INSTALADA")
    vendas_semana = (
        Venda.objects.filter(
            ativo=True,
        )
        .filter(status_instalada)
        .filter(_filtro_data_efetiva_instalacao_intervalo_venda(seg, sab))
        .select_related("vendedor", "cliente", "forma_pagamento", "plano")
    )

    # Por vendedor: CNPJ, cartão e total de vendas (receita operadora na semana)
    cartao_por_usuario: dict[int, int] = {}
    total_vendas_por_usuario: dict[int, Decimal] = {}
    for v in vendas_semana:
        if not v.vendedor_id:
            continue
        uid = v.vendedor_id
        if _is_cartao_credito(v.forma_pagamento):
            cartao_por_usuario[uid] = cartao_por_usuario.get(uid, 0) + 1
        # Valor que a empresa recebe da operadora por essa venda (Recebimento Operador)
        if v.plano_id and v.plano_id in mapa_comissao_op:
            cfg = mapa_comissao_op[v.plano_id]
            valor_venda = cfg["base"]
            if cfg["bonus"] and (not cfg["fim_bonus"] or (v.data_instalacao and v.data_instalacao <= cfg["fim_bonus"])):
                valor_venda += cfg["bonus"]
            total_vendas_por_usuario[uid] = total_vendas_por_usuario.get(uid, Decimal("0")) + valor_venda

    # Lançamentos financeiros na semana
    lancamentos = LancamentoFinanceiro.objects.filter(
        data__range=(seg, sab),
        usuario__in=usuarios,
    ).values("usuario_id", "tipo").annotate(soma=Sum("valor"))

    adiant_comissao: dict[int, Decimal] = {}
    adiant_cnpj: dict[int, Decimal] = {}
    desconto_avulso: dict[int, Decimal] = {}
    for row in lancamentos:
        uid = row["usuario_id"]
        val = Decimal(str(row["soma"] or 0))
        if row["tipo"] == "ADIANTAMENTO_COMISSAO":
            adiant_comissao[uid] = adiant_comissao.get(uid, Decimal("0")) + val
        elif row["tipo"] == "ADIANTAMENTO_CNPJ":
            adiant_cnpj[uid] = adiant_cnpj.get(uid, Decimal("0")) + val
        elif row["tipo"] == "DESCONTO":
            desconto_avulso[uid] = desconto_avulso.get(uid, Decimal("0")) + val
    qtd_cnpj_por_usuario: dict[int, int] = {}
    lancamentos_cnpj_qtd = (
        LancamentoFinanceiro.objects.filter(
            data__range=(seg, sab),
            usuario__in=usuarios,
            tipo='ADIANTAMENTO_CNPJ',
        )
        .values('usuario_id')
        .annotate(qtd=Sum('quantidade_vendas'))
    )
    for row in lancamentos_cnpj_qtd:
        qtd_cnpj_por_usuario[row['usuario_id']] = int(row['qtd'] or 0)

    # Campanhas que terminam na semana (prêmio pago naquela semana) – simplificado: 0 por enquanto
    # TODO: regra de negócio para valor_campanha por vendedor na semana
    valor_campanha_por_usuario: dict[int, Decimal] = {}

    # Montar linha por usuário
    resultado = []
    for user in usuarios:
        nome = (user.get_full_name() or "").strip() or (user.username or "").upper()
        val_passagem = Decimal(str(user.valor_passagem or 0))
        val_almoco = Decimal(str(user.valor_almoco or 0))
        valor_diario = val_almoco + val_passagem

        # Só considera faltas/retirada quem participa do controle de presença
        qtd_faltas = 0
        if user.participa_controle_presenca:
            user_records = mapa_presencas.get(user.id, {})
            for dia in dias_uteis:
                rec = user_records.get(dia)
                if rec:
                    if rec["status"] is False and rec["gera_desconto"]:
                        qtd_faltas += 1
                else:
                    qtd_faltas += 1
        retirada = Decimal(qtd_faltas) * valor_diario

        total_cnpj = adiant_cnpj.get(user.id, Decimal("0"))
        premiacao_cartao = (cartao_por_usuario.get(user.id, 0)) * VALOR_PREMIACAO_CARTAO
        adiantamento_solicitado = adiant_comissao.get(user.id, Decimal("0"))
        valor_avulso = desconto_avulso.get(user.id, Decimal("0"))  # descontos (valor positivo a subtrair)
        valor_campanha = valor_campanha_por_usuario.get(user.id, Decimal("0"))
        total_vendas = total_vendas_por_usuario.get(user.id, Decimal("0"))  # receita operadora na semana

        # Total: (valor_diario * dias) - retirada + cnpj + premiação + adiant.solicitado - valor_avulso + campanha
        base_semana = valor_diario * qtd_dias_semana
        total_a_receber = (
            base_semana
            - retirada
            + total_cnpj
            + premiacao_cartao
            + adiantamento_solicitado
            - valor_avulso
            + valor_campanha
        )

        resultado.append({
            "usuario_id": user.id,
            "nome": nome,
            "username": user.username or "",
            "valor_passagem": float(val_passagem),
            "valor_almoco": float(val_almoco),
            "qtd_dias_semana": qtd_dias_semana,
            "qtd_faltas": qtd_faltas,
            "retirada_faltas": float(retirada),
            "qtd_cnpj": qtd_cnpj_por_usuario.get(user.id, 0),
            "total_cnpj": float(total_cnpj),
            "qtd_cartao": cartao_por_usuario.get(user.id, 0),
            "premiacao_cartao": float(premiacao_cartao),
            "adiantamento_solicitado": float(adiantamento_solicitado),
            "valor_avulso": float(valor_avulso),
            "valor_campanha": float(valor_campanha),
            "total_vendas": float(total_vendas),
            "total_a_receber": float(total_a_receber),
        })

    return resultado
