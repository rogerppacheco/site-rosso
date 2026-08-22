"""
HTML único para PDF da folha de comissão (layout alinhado à tela) + extrato.
Usado no envio WhatsApp (um arquivo PDF em vez de imagem + PDF separado).
"""
from __future__ import annotations

import html as html_module
from typing import Any, Dict, List


def _fmt_br(val: Any) -> str:
    try:
        n = float(val)
        s = f"{n:,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def _e(s: Any) -> str:
    return html_module.escape(str(s) if s is not None else "")


def _plano_linha_visivel(p: Dict[str, Any]) -> bool:
    qtd_ant = int(p.get("qtd_antecipada") or 0)
    val_adiant = p.get("valor_total_antecipado")
    if val_adiant is None:
        val_adiant = 0
    try:
        val_adiant = float(val_adiant)
    except (TypeError, ValueError):
        val_adiant = 0.0
    return (
        int(p.get("qtd_instalada_a_pagar") or 0) > 0
        or qtd_ant > 0
        or float(p.get("valor_total_instalados") or 0) > 0
        or val_adiant > 0
    )


def _agrupar_descontos(detalhes: List[Dict[str, Any]]):
    tipos_agrupados = {
        "folha_boleto_vendas",
        "folha_antecipacao_instalacao",
        "adiant_cnpj",
        "adiant_comissao",
        "churn_m0",
        "churn_m1",
        "boleto",
        "antecipacao_instalacao",
        "processamento_auto_misto",
    }

    def filtro(codigo: str):
        return [x for x in detalhes if (x.get("tipo_exibicao") or "").lower() == codigo]

    folha_boleto = filtro("folha_boleto_vendas")
    folha_antecip = filtro("folha_antecipacao_instalacao")
    adiant = filtro("adiant_cnpj")
    churn_m0 = filtro("churn_m0")
    churn_m1 = filtro("churn_m1")
    outros = [x for x in detalhes if (x.get("tipo_exibicao") or "").lower() not in tipos_agrupados]
    return folha_boleto, folha_antecip, adiant, churn_m0, churn_m1, outros


def montar_html_folha_e_extrato_pdf(vendedor_data: Dict[str, Any], periodo: str) -> str:
    r = vendedor_data.get("resumo") or {}
    por_plano: List[Dict[str, Any]] = list(r.get("por_plano") or [])
    nome_v = _e(vendedor_data.get("vendedor_nome") or "")
    faixa = _e(r.get("faixa_aplicada") or "-")
    periodo_e = _e(periodo)
    qtd_instalados = r.get("qtd_instalada_faixa_complemento")
    if qtd_instalados is None:
        qtd_instalados = r.get("total_qtd_vendas_folha")
    qtd_instalados_s = _e(qtd_instalados if qtd_instalados is not None else "-")

    sum_q_ant = 0
    sum_val_adiant = 0.0
    sum_val_comp = 0.0
    sum_val_tot_inst = 0.0
    linhas_plano: List[str] = []

    for p in por_plano:
        if not _plano_linha_visivel(p):
            continue
        q_ap = int(p.get("qtd_instalada_a_pagar") or 0)
        q_ant = int(p.get("qtd_antecipada") or 0)
        v_adiant = p.get("valor_total_antecipado")
        v_comp = p.get("valor_total_complemento_sabado")
        try:
            v_adiant_f = float(v_adiant) if v_adiant is not None else 0.0
        except (TypeError, ValueError):
            v_adiant_f = 0.0
        try:
            v_comp_f = float(v_comp) if v_comp is not None else 0.0
        except (TypeError, ValueError):
            v_comp_f = 0.0
        sum_q_ant += q_ant
        sum_val_adiant += v_adiant_f
        sum_val_comp += v_comp_f
        v_tot = float(p.get("valor_total_instalados") or 0)
        sum_val_tot_inst += v_tot

        v_unit = p.get("valor_unitario_instalados")
        v_unit_s = _fmt_br(v_unit) if v_unit is not None else "—"
        if q_ant > 0:
            cell_adiant = _fmt_br(v_adiant_f)
            if v_comp_f != 0:
                cell_adiant += " (+ " + _fmt_br(v_comp_f) + " comp.)"
        else:
            cell_adiant = "—"

        linhas_plano.append(
            "<tr>"
            f"<td>{_e(p.get('plano') or '')}</td>"
            f'<td class="c">{q_ap}</td>'
            f'<td class="c">{q_ant}</td>'
            f'<td class="r info">{cell_adiant}</td>'
            f'<td class="r">{v_unit_s}</td>'
            f'<td class="r">{_fmt_br(v_tot)}</td>'
            f'<td class="r b">{_fmt_br(p.get("comissao_total") or 0)}</td>'
            "</tr>"
        )

    total_q_pagar = int(r.get("total_qtd_instalada_a_pagar") or 0)
    total_row = (
        '<tr class="total">'
        "<td><b>TOTAL</b></td>"
        f'<td class="c"><b>{total_q_pagar}</b></td>'
        f'<td class="c"><b>{sum_q_ant}</b></td>'
        f'<td class="r info"><b>{_fmt_br(sum_val_adiant) if sum_q_ant > 0 else "—"}'
        + (f" (+ {_fmt_br(sum_val_comp)} comp.)" if sum_val_comp != 0 and sum_q_ant > 0 else "")
        + '</b></td>'
        '<td class="r">—</td>'
        f'<td class="r"><b>{_fmt_br(sum_val_tot_inst)}</b></td>'
        f'<td class="r b"><b>{_fmt_br(r.get("comissao_total_geral") or 0)}</b></td>'
        "</tr>"
    )

    parts: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml">',
        "<head>",
        '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>',
        "<style>",
        "@page { size: A4 landscape; margin: 8mm; }",
        "body { font-family: Helvetica, Arial, sans-serif; font-size: 9px; color: #212529; }",
        "h1 { font-size: 13px; margin: 0; font-weight: bold; color: inherit; }",
        "h2 { font-size: 11px; margin: 16px 0 8px 0; border-bottom: 1px solid #dee2e6; padding-bottom: 4px; clear: both; }",
        ".hdr { background-color: #0d6efd; color: #ffffff; padding: 10px 12px; margin-bottom: 12px; }",
        ".hdr, .hdr table, .hdr td, .hdr th, .hdr h1, .hdr div { color: #ffffff !important; }",
        "table.hdr-bar { width: 100%; border-collapse: collapse; table-layout: fixed; background-color: #0d6efd; }",
        "table.hdr-bar td { border: none; vertical-align: middle; padding: 6px 8px; background-color: #0d6efd; }",
        ".hdr-faixa { width: 26%; font-size: 9px; text-align: left; font-weight: bold; }",
        ".hdr-nome { width: 48%; text-align: center; }",
        ".hdr-nome h1 { font-size: 14px; color: #ffffff !important; }",
        ".hdr-periodo { width: 26%; font-size: 9px; text-align: right; font-weight: bold; }",
        ".hdr-meta { font-size: 9px; color: #212529; margin: 0 0 12px 0; padding: 8px 10px; background: #f8f9fa; border: 1px solid #dee2e6; clear: both; }",
        "table.folha { width: 100%; border-collapse: collapse; margin-bottom: 8px; table-layout: fixed; }",
        "table.folha th, table.folha td { border: 1px solid #dee2e6; padding: 4px 5px; }",
        "table.folha th { background: #f8f9fa; font-weight: bold; text-align: left; }",
        "table.folha th.c, td.c { text-align: center; }",
        "table.folha th.r, td.r { text-align: right; }",
        "table.folha tr.total td { background: #f8f9fa; }",
        "td.b { font-weight: bold; }",
        "td.info { color: #0dcaf0; }",
        ".resumo-vendas { margin: 8px 0; font-size: 9px; padding: 6px 8px; background: #f8f9fa; border: 1px solid #dee2e6; }",
        "table.resumo-financeiro { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9px; }",
        "table.resumo-financeiro td { border: 1px solid #dee2e6; padding: 6px 8px; text-align: center; vertical-align: middle; }",
        "table.resumo-financeiro td.liquido { font-size: 10px; font-weight: bold; }",
        ".neg { color: #dc3545; font-weight: bold; }",
        ".pos { color: #198754; font-weight: bold; }",
        ".aviso { background: #fff3cd; border: 1px solid #ffc107; padding: 6px; margin: 8px 0; font-size: 8px; }",
        ".bloco { margin-top: 10px; margin-bottom: 10px; font-size: 8px; width: 100%; clear: both; }",
        ".bloco-tit { color: #6c757d; font-weight: bold; margin: 8px 0 6px 0; display: block; }",
        ".bloco .neg, .bloco .pos, .bloco div { display: block; margin: 4px 0; line-height: 1.35; }",
        ".ref-linha { color: #0dcaf0; display: block; margin: 6px 0; }",
        ".ref-plano { color: #6c757d; margin: 3px 0 3px 10px; display: block; }",
        "table.extrato { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 0; }",
        "table.extrato th, table.extrato td { border: 1px solid #dee2e6; padding: 3px 4px; font-size: 7px; vertical-align: top; word-wrap: break-word; }",
        "table.extrato th { background: #f8f9fa; font-size: 6.5px; }",
        "table.extrato th.c, table.extrato td.c { text-align: center; }",
        "table.extrato th.ex-nome, table.extrato td.ex-nome { width: 17%; text-align: left; }",
        "table.extrato th.ex-dacc, table.extrato td.ex-dacc, table.extrato th.ex-cnpj, table.extrato td.ex-cnpj { width: 4%; }",
        "table.extrato th.ex-plano, table.extrato td.ex-plano { width: 9%; }",
        "table.extrato th.ex-dtped, table.extrato td.ex-dtped, table.extrato th.ex-dtinst, table.extrato td.ex-dtinst { width: 7%; }",
        "table.extrato th.ex-os, table.extrato td.ex-os { width: 9%; }",
        "table.extrato th.ex-sit, table.extrato td.ex-sit { width: 24%; text-align: left; }",
        "table.extrato th.ex-churn, table.extrato td.ex-churn, table.extrato th.ex-adiant, table.extrato td.ex-adiant { width: 5%; }",
        "table.extrato th.ex-comissao, table.extrato td.ex-comissao { width: 7%; text-align: right; }",
        ".row-danger { background-color: #f8d7da; }",
        ".row-success { background-color: #d4edda; }",
        ".row-warning { background-color: #fff3cd; }",
        ".bloco-row { background: #e9ecef; color: #212529; font-weight: bold; }",
        "</style>",
        "</head><body>",
        '<div class="hdr">'
        '<table class="hdr-bar" border="0" cellpadding="0" cellspacing="0"><tr>'
        '<td class="hdr-faixa">Faixa: ' + faixa + " | Instalados: " + qtd_instalados_s + "</td>"
        '<td class="hdr-nome"><h1>' + nome_v + "</h1></td>"
        '<td class="hdr-periodo">Período: ' + periodo_e + "</td>"
        "</tr></table></div>"
        '<div class="hdr-meta">'
        "<strong>Vendedor:</strong> "
        + nome_v
        + " | <strong>Período:</strong> "
        + periodo_e
        + " | <strong>Faixa:</strong> "
        + faixa
        + " | <strong>Instalados:</strong> "
        + qtd_instalados_s
        + "</div>",
        '<table class="folha">',
        "<thead><tr>",
        "<th>PLANO</th>",
        '<th class="c">QTD A PAGAR</th>',
        '<th class="c">QTD ANTECIPADA</th>',
        '<th class="r">VALOR JÁ ADIANT.</th>',
        '<th class="r">VALOR UNIT.</th>',
        '<th class="r">VALOR TOTAL</th>',
        '<th class="r">COMISSÃO</th>',
        "</tr></thead><tbody>",
        "".join(linhas_plano),
        total_row,
        "</tbody></table>",
        '<div class="resumo-vendas">'
        "<strong>Total vendas a pagar:</strong> "
        + _e(total_q_pagar)
        + " | <strong>Total vendas antecipadas:</strong> "
        + _e(sum_q_ant)
        + " | <strong>Total vendas no mês (pagas):</strong> "
        + _e(
            r.get("total_qtd_vendas_folha")
            if r.get("total_qtd_vendas_folha") is not None
            else (total_q_pagar + sum_q_ant)
        )
        + "</div>",
        '<table class="resumo-financeiro"><tr>',
        "<td><strong>Comissão (a pagar):</strong><br/>"
        + _fmt_br(r.get("comissao_total_geral") or 0)
        + "</td>",
    ]
    comp_sab = float(r.get("complemento_sabado_total") or 0)
    if comp_sab != 0:
        parts.append(
            '<td class="pos"><strong>Complemento sábado:</strong><br/>+ '
            + _fmt_br(comp_sab)
            + "</td>"
        )
    parts.extend([
        '<td class="neg"><strong>Descontos:</strong><br/>- '
        + _fmt_br(r.get("total_descontos") or 0)
        + "</td>",
        '<td class="pos"><strong>Bônus:</strong><br/>+ '
        + _fmt_br(r.get("total_bonus") or 0)
        + "</td>",
        '<td class="liquido pos"><strong>LÍQUIDO A PAGAR:</strong><br/>'
        + _fmt_br(r.get("liquido") or 0)
        + "</td>",
        "</tr></table>",
    ])

    if r.get("desconta_boleto_pap") is False:
        parts.append(
            '<div class="aviso">Regras por vendedor: <b>boleto não desconta no líquido</b>. '
            "A linha de boleto abaixo mostra o valor cheio (informativo); o total de descontos já está sem esse valor.</div>"
        )

    detalhes = list(r.get("detalhes_descontos") or [])
    if detalhes:
        folha_boleto, folha_antecip, adiant, churn_m0, churn_m1, outros = _agrupar_descontos(detalhes)
        parts.append('<div class="bloco"><div class="bloco-tit">Lançamentos descontados</div>')
        qadc = r.get("qtd_a_descontar")
        if qadc is not None and int(qadc) > 0:
            parts.append('<div style="color:#6c757d;font-weight:bold;margin-bottom:4px;">QTD A DESCONTAR: ' + _e(qadc) + "</div>")

        def linha_desconto(d: Dict[str, Any]) -> str:
            motivo = _e(d.get("motivo") or "Desconto")
            q = d.get("quantidade")
            if q is not None and q != "":
                motivo += " (" + _e(q) + " un.)"
            return f'<div class="neg">{motivo}: - {_fmt_br(d.get("valor") or 0)}</div>'

        for d in folha_boleto:
            parts.append(linha_desconto(d))
        for d in folha_antecip:
            parts.append(linha_desconto(d))
        if adiant:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Adiant. CNPJ</div>')
            for d in adiant:
                parts.append(linha_desconto(d))
        if churn_m0:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Desconto Churn M0</div>')
            for d in churn_m0:
                parts.append(linha_desconto(d))
        if churn_m1:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Desconto Churn M-1</div>')
            for d in churn_m1:
                parts.append(linha_desconto(d))
        if outros:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Outros</div>')
            for d in outros:
                parts.append(linha_desconto(d))
        parts.append("</div>")

    info_ad = r.get("info_comissao_adiantada") or {}
    if int(info_ad.get("quantidade_total") or 0) > 0:
        parts.append('<div class="bloco"><div class="bloco-tit">Referência — não entra em descontos</div>')
        parts.append(
            '<div class="ref-linha">Comissão já adiantada (esteira + tabela Adiantamento) <b>('
            + _e(info_ad.get("quantidade_total"))
            + " un.)</b> → "
            + _fmt_br(info_ad.get("valor_total") or 0)
            + "</div>"
        )
        for row in info_ad.get("por_plano") or []:
            if int(row.get("qtd") or 0) > 0:
                parts.append(
                    '<div class="ref-plano">'
                    + _e(row.get("plano"))
                    + ": "
                    + _e(row.get("qtd"))
                    + " un. → "
                    + _fmt_br(row.get("valor_total") or 0)
                    + "</div>"
                )
        parts.append("</div>")

    bonus = list(r.get("detalhes_bonus") or [])
    if bonus:
        parts.append('<div class="bloco"><div class="bloco-tit">Bônus / premiação</div>')
        for b in bonus:
            parts.append(
                '<div class="pos">'
                + _e(b.get("motivo") or "Bônus/Premiação")
                + ": + "
                + _fmt_br(b.get("valor") or 0)
                + "</div>"
            )
        parts.append("</div>")

    extrato = list(vendedor_data.get("extrato") or [])

    def _norm(v: Any) -> str:
        return str(v or "").strip().upper()

    def _date_key_br(v: Any):
        s = str(v or "").strip()
        p = s.split("/")
        if len(p) != 3:
            return (9999, 99, 99)
        try:
            dd, mm, yyyy = int(p[0]), int(p[1]), int(p[2])
            return (yyyy, mm, dd)
        except (TypeError, ValueError):
            return (9999, 99, 99)

    def _bloco_info(e: Dict[str, Any]):
        situacao = _norm(e.get("situacao"))
        is_churn = _norm(e.get("churn")) == "SIM"
        is_cancelada = "CANCELADA" in situacao
        if situacao == "INSTALADA" and not is_churn:
            return (0, "INSTALADAS")
        if situacao == "INSTALADA" and is_churn:
            return (1, "INSTALADAS COM CHURN")
        if is_cancelada:
            return (2, "CANCELADAS")
        return (3, "DEMAIS STATUS")

    blocos = [
        {"ordem": 0, "titulo": "INSTALADAS", "itens": []},
        {"ordem": 1, "titulo": "INSTALADAS COM CHURN", "itens": []},
        {"ordem": 2, "titulo": "CANCELADAS", "itens": []},
        {"ordem": 3, "titulo": "DEMAIS STATUS", "itens": []},
    ]
    for e in extrato:
        ordem, _titulo = _bloco_info(e)
        blocos[ordem]["itens"].append(e)

    parts.append(
        "<h2>Extrato (" + str(len(extrato)) + " vendas)</h2>"
        '<table class="extrato">'
        "<thead><tr>"
        '<th class="ex-nome" style="width:17%">NOME</th>'
        '<th class="ex-dacc c" style="width:4%">DACC</th>'
        '<th class="ex-cnpj c" style="width:4%">CNPJ</th>'
        '<th class="ex-plano" style="width:9%">PLANO</th>'
        '<th class="ex-dtped c" style="width:7%">DT PEDIDO</th>'
        '<th class="ex-dtinst c" style="width:7%">DT INST</th>'
        '<th class="ex-os c" style="width:9%">OS</th>'
        '<th class="ex-sit" style="width:33%">SITUAÇÃO</th>'
        '<th class="ex-churn c" style="width:5%">CHURN</th>'
        '<th class="ex-adiant c" style="width:5%">ADIANT.</th>'
        '<th class="ex-comissao r" style="width:7%">COMISSÃO</th>'
        '<th class="ex-tipo" style="width:12%">TIPO COMISSÃO</th>'
        "</tr></thead><tbody>"
    )

    for b in blocos:
        if not b["itens"]:
            continue
        parts.append(
            f'<tr class="bloco-row"><td colspan="11">{_e(b["titulo"])} — {len(b["itens"])} venda(s)</td></tr>'
        )
        itens = sorted(
            b["itens"],
            key=lambda x: (_date_key_br(x.get("dt_pedido")), str(x.get("nome") or "").upper()),
        )
        for e in itens:
            churn_sim = _norm(e.get("churn")) == "SIM"
            adiant_sim = _norm(e.get("adiantada")) == "SIM"
            situacao = _norm(e.get("situacao"))
            is_cancelada = "CANCELADA" in situacao
            is_instalada = situacao == "INSTALADA"
            is_verde = is_instalada and not churn_sim
            cls = "row-danger" if (churn_sim or is_cancelada) else ("row-success" if is_verde else "row-warning")
            style = ' style="background-color:#cfe8d6;"' if (is_verde and adiant_sim) else ""
            val_com = e.get("valor_comissao")
            val_com_txt = _fmt_br(val_com) if val_com is not None else "—"
            parts.append(
                f'<tr class="{cls}"{style}>'
                f'<td class="ex-nome">{_e(e.get("nome"))}</td>'
                f'<td class="ex-dacc c">{_e(e.get("dacc"))}</td>'
                f'<td class="ex-cnpj c">{_e(e.get("cnpj"))}</td>'
                f'<td class="ex-plano">{_e(e.get("plano"))}</td>'
                f'<td class="ex-dtped c">{_e(e.get("dt_pedido"))}</td>'
                f'<td class="ex-dtinst c">{_e(e.get("dt_inst"))}</td>'
                f'<td class="ex-os c">{_e(e.get("os"))}</td>'
                f'<td class="ex-sit">{_e(e.get("situacao"))}</td>'
                f'<td class="ex-churn c">{_e(e.get("churn"))}</td>'
                f'<td class="ex-adiant c">{_e(e.get("adiantada") or "—")}</td>'
                f'<td class="ex-comissao r">{val_com_txt}</td>'
                f'<td class="ex-tipo">{_e(e.get("comissao_tipo") or "—")}</td>'
                "</tr>"
            )

    parts.append("</tbody></table></body></html>")
    return "".join(parts)
