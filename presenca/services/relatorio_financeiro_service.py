"""
Serviço do relatório financeiro de presença: dias úteis, previsão e apuração
com descontos por falta, e exportação Excel.

Centraliza a regra de negócio: valor diário (almoco + passagem) por colaborador,
dias úteis excluindo feriados e fins de semana, e desconto quando o colaborador
está ausente em dia útil com motivo que gera desconto (ou sem registro = falta).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
from django.http import HttpResponse

from presenca.models import DiaNaoUtil, Presenca
from usuarios.models import Usuario


def get_dias_uteis_periodo(inicio: date, fim: date) -> list[date]:
    """
    Retorna as datas de dias úteis entre inicio e fim, excluindo sábado, domingo
    e datas cadastradas em DiaNaoUtil (feriados).
    """
    feriados: set[date] = set(
        DiaNaoUtil.objects.filter(data__range=(inicio, fim)).values_list(
            "data", flat=True
        )
    )
    dias: list[date] = []
    atual = inicio
    while atual <= fim:
        if atual.weekday() < 5 and atual not in feriados:
            dias.append(atual)
        atual += timedelta(days=1)
    return dias


def gerar_relatorio_financeiro(
    dt_ini: date, dt_fim: date
) -> dict[str, list[dict[str, Any]]]:
    """
    Gera os dados do relatório financeiro: previsão (cenário ideal) e apuração
    real com faltas e descontos por colaborador que participa do controle de presença.

    Regra de desconto: falta = ausente em dia útil com motivo que gera desconto,
    ou sem nenhum registro no dia útil. O valor descontado é (qtd_faltas * valor_diario).
    """
    dias_uteis_lista = get_dias_uteis_periodo(dt_ini, dt_fim)
    qtd_dias_uteis = len(dias_uteis_lista)

    usuarios = Usuario.objects.filter(
        participa_controle_presenca=True, is_active=True
    ).order_by("first_name")

    presencas = Presenca.objects.filter(
        data__range=(dt_ini, dt_fim),
        colaborador__in=usuarios,
    ).select_related("motivo")

    mapa_presencas: dict[int, dict[date, dict[str, Any]]] = {}
    for p in presencas:
        uid = p.colaborador_id
        if uid not in mapa_presencas:
            mapa_presencas[uid] = {}
        gera_desconto = bool(
            not p.status and p.motivo and getattr(p.motivo, "gera_desconto", False)
        )
        mapa_presencas[uid][p.data] = {
            "status": p.status,
            "gera_desconto": gera_desconto,
        }

    dados_previsao: list[dict[str, Any]] = []
    dados_descontos: list[dict[str, Any]] = []

    for user in usuarios:
        nome_display = (user.get_full_name() or "").strip()
        if not nome_display:
            nome_display = (user.username or "").upper()
        else:
            nome_display = nome_display.upper()

        val_almoco = float(user.valor_almoco or 0)
        val_passagem = float(user.valor_passagem or 0)
        valor_diario = val_almoco + val_passagem
        total_previsao = qtd_dias_uteis * valor_diario

        dados_previsao.append({
            "nome": nome_display,
            "username": user.username or "",
            "dias_uteis": qtd_dias_uteis,
            "valor_diario": valor_diario,
            "total_receber": total_previsao,
        })

        user_records = mapa_presencas.get(user.id, {})
        datas_faltas: list[date] = []
        for dia in dias_uteis_lista:
            rec = user_records.get(dia)
            if rec:
                if rec["status"] is False and rec["gera_desconto"] is True:
                    datas_faltas.append(dia)
            else:
                datas_faltas.append(dia)

        qtd_faltas = len(datas_faltas)
        valor_desconto = qtd_faltas * valor_diario
        total_liquido = total_previsao - valor_desconto

        dados_descontos.append({
            "nome": nome_display,
            "username": user.username or "",
            "dias_uteis": qtd_dias_uteis,
            "qtd_faltas": qtd_faltas,
            "datas_faltas": [d.strftime("%d/%m/%Y") for d in datas_faltas],
            "valor_diario": valor_diario,
            "valor_desconto": valor_desconto,
            "total_receber": total_liquido,
        })

    return {"previsao": dados_previsao, "descontos": dados_descontos}


def gerar_excel_http(
    dt_ini: date, dt_fim: date, inicio_str: str, fim_str: str
) -> HttpResponse:
    """
    Gera o arquivo Excel do relatório financeiro (apurado) e retorna uma
    HttpResponse com content-type e Content-Disposition para download.
    """
    dados = gerar_relatorio_financeiro(dt_ini, dt_fim)
    lista_final = dados["descontos"]

    export_list = [
        {
            "Colaborador": item["nome"],
            "Username": item.get("username", ""),
            "Dias Úteis": item["dias_uteis"],
            "Valor Diário (R$)": item["valor_diario"],
            "Previsão Total (R$)": item["dias_uteis"] * item["valor_diario"],
            "Qtd Faltas": item["qtd_faltas"],
            "Valor Desconto (R$)": item["valor_desconto"],
            "Total a Receber (R$)": item["total_receber"],
            "Datas das Faltas": ", ".join(item["datas_faltas"]),
        }
        for item in lista_final
    ]

    df = pd.DataFrame(export_list)
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"Financeiro_{inicio_str}_{fim_str}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    with pd.ExcelWriter(response, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Financeiro")

    return response
