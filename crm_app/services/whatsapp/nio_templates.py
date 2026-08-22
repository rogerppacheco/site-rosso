"""
Templates Meta Nio (Número B / WhatsAtende Cloud API).

Envio fora da janela 24h e fluxos oficiais (confirmação, instalação, cobrança).
Botões Quick Reply chegam no webhook como texto do botão.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Nomes aprovados / em aprovação na WABA (conexão #194)
TEMPLATE_CONFIRMACAO_PEDIDO = "nio_confirmacao_pedido_v1"
TEMPLATE_LEMBRETE_INSTALACAO = "nio_lembrete_instalacao_v1"
TEMPLATE_INSTALACAO_CONFIRMADA = "nio_instalacao_confirmada_v1_2"
TEMPLATE_FATURA_LEMBRETE_5D = "nio_fatura_lembrete_5d_antes_v1"
TEMPLATE_FATURA_VENCIDA_5D = "nio_fatura_vencida_5d_v1"
TEMPLATE_FATURA_RECORRENTE = "nio_fatura_cobranca_recorrente_v1"
TEMPLATE_FATURA_REDUCAO_SINAL = "nio_fatura_reducao_sinal_v1"
TEMPLATE_PENDENCIA_REAGENDAMENTO = "nio_pendencia_reagendamento_v1"
TEMPLATE_BOAS_VINDAS = "nio_boas_vindas_v1"

NIO_WHATSAPP_OFICIAL_EXIBICAO = "21 3605-1000"

LANGUAGE_PT_BR = "pt_BR"

# Respostas de botão (texto que o cliente envia ao clicar)
BTN_CORRETO = "CORRETO"
BTN_CORRIGIR = "CORRIGIR"
BTN_FALAR_ATENDENTE = "FALAR COM ATENDENTE"
BTN_CONFIRMAR = "CONFIRMAR"
BTN_REAGENDAR = "REAGENDAR"
BTN_SUPORTE = "SUPORTE"
BTN_ENTENDI = "ENTENDI"
BTN_SEGUNDA_VIA = "QUERO A 2A VIA"
BTN_JA_PAGUEI = "JA PAGUEI"
BTN_FALAR_SUPORTE = "FALAR COM SUPORTE"
BTN_INFORMAR_PREVISAO = "INFORMAR PREVISAO"


def templates_habilitados() -> bool:
    """Usa templates Meta quando o canal cliente é Cloud API (WhatsAtende B / hybrid)."""
    flag = getattr(settings, "WHATSAPP_USE_NIO_TEMPLATES", None)
    if flag is not None:
        return bool(flag)
    try:
        from crm_app.services.whatsapp_config_service import cliente_usa_cloud_api

        return cliente_usa_cloud_api()
    except Exception:
        provider = (getattr(settings, "WHATSAPP_PROVIDER", "") or "").strip().lower()
        return provider in ("whatsatende", "hybrid")


def saudacao_meta(agora: Optional[datetime] = None) -> str:
    """
    Saudação para {{1}} dos templates (fuso America/Sao_Paulo via TIME_ZONE).
    05–11 Bom dia | 12–17 Boa tarde | 18–04 Boa noite
    """
    dt = agora or timezone.localtime()
    hora = dt.hour
    if 5 <= hora <= 11:
        return "Bom dia"
    if 12 <= hora <= 17:
        return "Boa tarde"
    return "Boa noite"


def primeiro_nome(nome_completo: Optional[str]) -> str:
    nome = (nome_completo or "").strip()
    if not nome:
        return "Cliente"
    return nome.split()[0]


def mascarar_cpf(cpf: Optional[str]) -> str:
    digitos = re.sub(r"\D", "", cpf or "")
    if len(digitos) != 11:
        return "***.***.***-**"
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


def mascarar_email(email: Optional[str]) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return "***@***.***"
    local, _, dominio = e.partition("@")
    if not local:
        return f"***@{dominio}"
    if len(local) == 1:
        return f"{local}***@{dominio}"
    return f"{local[0]}***{local[-1]}@{dominio}"


def _fmt_cep(cep: Optional[str]) -> str:
    digitos = re.sub(r"\D", "", cep or "")
    if len(digitos) == 8:
        return f"{digitos[:5]}-{digitos[5:]}"
    return (cep or "").strip() or "-"


def _fmt_moeda(valor: Any) -> str:
    try:
        from crm_app.services.gdp_preco_service import formatar_moeda_br

        return formatar_moeda_br(valor)
    except Exception:
        try:
            n = float(valor)
            return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return "R$ 0,00"


def _fmt_data(d: Any) -> str:
    if isinstance(d, datetime):
        d = timezone.localtime(d).date() if timezone.is_aware(d) else d.date()
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    s = str(d or "").strip()
    return s or "-"


def normalizar_texto_botao(texto: Optional[str]) -> str:
    """Uppercase sem acento para casar Quick Reply Meta com handlers."""
    raw = (texto or "").strip()
    if not raw:
        return ""
    nfkd = unicodedata.normalize("NFKD", raw)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).upper().replace("ª", "A").replace("º", "O")


def classificar_botao(texto: Optional[str]) -> Optional[str]:
    """Retorna constante BTN_* ou None."""
    n = normalizar_texto_botao(texto)
    if not n:
        return None
    mapa = {
        "CORRETO": BTN_CORRETO,
        "CORRIGIR": BTN_CORRIGIR,
        "FALAR COM ATENDENTE": BTN_FALAR_ATENDENTE,
        "CONFIRMAR": BTN_CONFIRMAR,
        "REAGENDAR": BTN_REAGENDAR,
        "SUPORTE": BTN_SUPORTE,
        "ENTENDI": BTN_ENTENDI,
        "QUERO A 2A VIA": BTN_SEGUNDA_VIA,
        "QUERO A 2 VIA": BTN_SEGUNDA_VIA,
        "JA PAGUEI": BTN_JA_PAGUEI,
        "FALAR COM SUPORTE": BTN_FALAR_SUPORTE,
        "INFORMAR PREVISAO": BTN_INFORMAR_PREVISAO,
        "INFORMAR PREVISAO DE PAGAMENTO": BTN_INFORMAR_PREVISAO,
    }
    if n in mapa:
        return mapa[n]
    # Fallbacks curtos
    if n in ("SIM", "S", "CONFIRMO", "OK"):
        return BTN_CONFIRMAR
    return None


def body_params_confirmacao_venda(venda: Any) -> List[str]:
    """14 variáveis de nio_confirmacao_pedido_v1 a partir de Venda."""
    cliente = getattr(venda, "cliente", None)
    nome = ""
    cpf = ""
    email = ""
    if cliente is not None:
        nome = (getattr(cliente, "nome_razao_social", None) or "").strip()
        cpf = getattr(cliente, "cpf_cnpj", None) or ""
        email = getattr(cliente, "email", None) or ""

    complemento = (getattr(venda, "complemento", None) or "").strip() or "-"
    cidade = (getattr(venda, "cidade", None) or "").strip()
    uf = (getattr(venda, "estado", None) or "").strip()
    cidade_uf = f"{cidade} - {uf}".strip(" -") if (cidade or uf) else "-"

    forma = ""
    if getattr(venda, "forma_pagamento", None):
        forma = (venda.forma_pagamento.nome or "").strip()
    forma = forma or "Boleto"

    plano_linha = "Não informado"
    if getattr(venda, "plano", None):
        try:
            from crm_app.services.gdp_preco_service import (
                VALOR_FIXO_NIO_MENSAL,
                formatar_moeda_br,
                resolver_valor_plano_venda,
            )

            valor_plano, _ = resolver_valor_plano_venda(venda)
            plano_linha = f"{venda.plano.nome} - {formatar_moeda_br(valor_plano)}/mês"
            if getattr(venda, "tem_fixo", False):
                total = float(valor_plano) + float(VALOR_FIXO_NIO_MENSAL)
                plano_linha = (
                    f"{venda.plano.nome} - {formatar_moeda_br(valor_plano)}/mês "
                    f"+ Fixo {formatar_moeda_br(VALOR_FIXO_NIO_MENSAL)}/mês "
                    f"= {formatar_moeda_br(total)}/mês"
                )
        except Exception as exc:
            logger.warning("[NioTemplates] plano venda=%s: %s", getattr(venda, "id", "?"), exc)
            plano_linha = getattr(venda.plano, "nome", None) or plano_linha

    return [
        saudacao_meta(),
        primeiro_nome(nome),
        nome or "Cliente",
        mascarar_cpf(cpf),
        mascarar_email(email),
        _fmt_cep(getattr(venda, "cep", None)),
        (getattr(venda, "logradouro", None) or "").strip() or "-",
        (getattr(venda, "numero_residencia", None) or "").strip() or "-",
        complemento,
        (getattr(venda, "bairro", None) or "").strip() or "-",
        cidade_uf,
        forma,
        plano_linha,
        "12 meses",
    ]


def body_params_confirmacao_pap(dados: Dict[str, Any]) -> List[str]:
    """14 variáveis a partir de dados_pedido do fluxo PAP."""
    nome = (dados.get("nome_cliente") or "Cliente").strip()
    cpf = dados.get("cpf") or dados.get("cpf_cnpj") or ""
    email = dados.get("email") or ""
    cep = dados.get("cep") or ""
    logradouro = (dados.get("logradouro") or dados.get("rua") or "").strip() or "-"
    numero = (dados.get("numero") or "").strip() or "-"
    complemento = (dados.get("complemento") or dados.get("referencia") or "").strip() or "-"
    bairro = (dados.get("bairro") or "").strip() or "-"
    cidade = (dados.get("cidade") or "").strip()
    uf = (dados.get("uf") or dados.get("estado") or "").strip()
    cidade_uf = f"{cidade} - {uf}".strip(" -") if (cidade or uf) else "-"

    plano = (dados.get("plano") or "500mega").upper()
    forma_raw = (dados.get("forma_pagamento") or "Boleto").strip().lower()
    cartao = "credito" in forma_raw or "cartao" in forma_raw or "cartão" in forma_raw
    valor_map = {
        "500MEGA": ("R$ 100,00/mês", "R$ 90,00/mês"),
        "700MEGA": ("R$ 130,00/mês", "R$ 120,00/mês"),
        "1GIGA": ("R$ 160,00/mês", "R$ 150,00/mês"),
    }
    par = valor_map.get(plano, ("R$ --/mês", "R$ --/mês"))
    valor = par[1] if cartao else par[0]
    plano_label = plano.replace("MEGA", " Mega").replace("GIGA", " Giga")
    forma_map = {
        "boleto": "Boleto",
        "cartao": "Cartão de Crédito",
        "cartão": "Cartão de Crédito",
        "debito": "Débito em Conta",
        "débito": "Débito em Conta",
    }
    forma = forma_map.get(forma_raw) or forma_raw.title()

    return [
        saudacao_meta(),
        primeiro_nome(nome),
        nome,
        mascarar_cpf(str(cpf)),
        mascarar_email(str(email)),
        _fmt_cep(str(cep)),
        logradouro,
        numero,
        complemento,
        bairro,
        cidade_uf or "-",
        forma,
        f"{plano_label} - {valor}",
        "12 meses",
    ]


def body_params_lembrete_instalacao(
    nome_cliente: str,
    data_agendamento: Any,
    periodo: str,
) -> List[str]:
    periodo_u = (periodo or "").strip().upper()
    if periodo_u in ("MANHA", "MANHÃ"):
        janela = "08:00 às 12:00"
    elif periodo_u in ("TARDE",):
        janela = "13:00 às 18:00"
    else:
        janela = (periodo or "").strip() or "a confirmar"
    data_txt = _fmt_data(data_agendamento)
    if isinstance(data_agendamento, date) and not isinstance(data_agendamento, datetime):
        # Preferência do template: dd/mm/yyyy; se for "hoje" o CRM já passa a data
        data_txt = data_agendamento.strftime("%d/%m/%Y")
    return [
        saudacao_meta(),
        primeiro_nome(nome_cliente),
        data_txt,
        janela,
    ]


def body_params_instalacao_confirmada(data_agendamento: Any, periodo: str) -> List[str]:
    """nio_instalacao_confirmada_v1_2: {{1}} data, {{2}} horário (sem saudação)."""
    periodo_u = (periodo or "").strip().upper()
    if periodo_u in ("MANHA", "MANHÃ"):
        janela = "08:00 às 12:00"
    elif periodo_u in ("TARDE",):
        janela = "13:00 às 18:00"
    else:
        janela = (periodo or "").strip() or "a confirmar"
    return [_fmt_data(data_agendamento), janela]


def body_params_pendencia_reagendamento(nome_cliente: str) -> List[str]:
    """nio_pendencia_reagendamento_v1: {{1}} saudação, {{2}} nome, {{3}} WhatsApp Nio."""
    return [
        saudacao_meta(),
        primeiro_nome(nome_cliente),
        NIO_WHATSAPP_OFICIAL_EXIBICAO,
    ]


def body_params_boas_vindas(nome_cliente: str) -> List[str]:
    """nio_boas_vindas_v1: {{1}} saudação, {{2}} nome (rascunho até aprovação Meta)."""
    return [saudacao_meta(), primeiro_nome(nome_cliente)]


def body_params_fatura(
    nome_cliente: str,
    referencia: str,
    valor: Any,
    vencimento: Any,
    *,
    dias_atraso: Optional[int] = None,
) -> List[str]:
    params = [
        saudacao_meta(),
        primeiro_nome(nome_cliente),
        (referencia or "-").strip() or "-",
        _fmt_moeda(valor) if not isinstance(valor, str) else (valor or "R$ 0,00"),
        _fmt_data(vencimento),
    ]
    if dias_atraso is not None:
        params.append(str(int(dias_atraso)))
    return params


def referencia_fatura(fatura: Any) -> str:
    if getattr(fatura, "numero_fatura_operadora", None):
        return str(fatura.numero_fatura_operadora).strip()
    venc = getattr(fatura, "data_vencimento", None)
    if isinstance(venc, date):
        meses = {
            1: "Janeiro",
            2: "Fevereiro",
            3: "Março",
            4: "Abril",
            5: "Maio",
            6: "Junho",
            7: "Julho",
            8: "Agosto",
            9: "Setembro",
            10: "Outubro",
            11: "Novembro",
            12: "Dezembro",
        }
        return f"{meses.get(venc.month, venc.month)}/{venc.year}"
    num = getattr(fatura, "numero_fatura", None)
    return f"Fatura {num}" if num else "Fatura Nio"


def montar_fallback_fatura_reducao_sinal(
    nome_cliente: str,
    fatura: Any,
) -> str:
    """Texto livre equivalente a nio_fatura_reducao_sinal_v1 (janela 24h / fallback)."""
    params = body_params_fatura(
        nome_cliente,
        referencia_fatura(fatura),
        getattr(fatura, "valor", 0),
        getattr(fatura, "data_vencimento", None),
    )
    saudacao, nome, ref, valor, venc = params[:5]
    return (
        f"Olá, {saudacao}!\n\n"
        f"{nome},\n\n"
        "Parceiro oficial da Nio Fibra.\n"
        "Sua internet está com a velocidade reduzida devido a uma pendência de pagamento.\n\n"
        f"Referência: *{ref}*\n"
        f"Valor: *{valor}*\n"
        f"Vencimento: *{venc}*\n\n"
        "Precisamos do seu retorno para programar a regularização e liberar "
        "novamente 100% do seu sinal de fibra óptica.\n\n"
        "Informe sua previsão de pagamento.\n\n"
        "SAC: 0800 001 1000 | WhatsApp: 21 3605-1000"
    )


def enviar_template_cliente(
    telefone: str,
    template_name: str,
    body_params: Sequence[str],
    *,
    language_code: str = LANGUAGE_PT_BR,
) -> Tuple[bool, Any]:
    """Envia template pelo Número B. Retorna (ok, resposta)."""
    from crm_app.whatsapp_service import WhatsAppService

    params = [str(p) if p is not None and str(p).strip() != "" else "-" for p in body_params]
    svc = WhatsAppService.para_cliente()
    return svc.enviar_template(
        telefone,
        template_name,
        language_code=language_code,
        body_params=params,
    )


def tentar_enviar_ou_texto(
    telefone: str,
    template_name: str,
    body_params: Sequence[str],
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    """
    Tenta template Meta; se desabilitado/falhar, envia texto livre.
    Retorna (ok, resposta, canal) com canal in ('template','texto').
    """
    from crm_app.whatsapp_service import WhatsAppService

    if templates_habilitados():
        ok, resp = enviar_template_cliente(telefone, template_name, body_params)
        if ok:
            return True, resp, "template"
        logger.warning(
            "[NioTemplates] Fallback texto após falha template=%s resp=%s",
            template_name,
            resp,
        )
    ok, resp = WhatsAppService.para_cliente().enviar_mensagem_texto(
        telefone, fallback_texto, variar=False
    )
    return bool(ok), resp, "texto"


def enviar_confirmacao_pedido_venda(venda: Any, telefone: str) -> Tuple[bool, Any, str]:
    from crm_app.utils import montar_resumo_plano_para_whatsapp

    params = body_params_confirmacao_venda(venda)
    fallback = montar_resumo_plano_para_whatsapp(venda)
    fallback = (
        f"{fallback}\n\nToque em *CORRETO* ou *CORRIGIR*, "
        "ou digite CONFIRMAR / CORRETO."
    )
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_CONFIRMACAO_PEDIDO, params, fallback
    )


def enviar_confirmacao_pedido_pap(telefone: str, dados: Dict[str, Any], resumo_txt: str) -> Tuple[bool, Any, str]:
    params = body_params_confirmacao_pap(dados)
    fallback = (
        f"{resumo_txt}\n\nToque em *CORRETO* ou digite *SIM* / *CORRETO* para confirmar."
    )
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_CONFIRMACAO_PEDIDO, params, fallback
    )


def enviar_lembrete_instalacao(
    telefone: str,
    nome_cliente: str,
    data_agendamento: Any,
    periodo: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    params = body_params_lembrete_instalacao(nome_cliente, data_agendamento, periodo)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_LEMBRETE_INSTALACAO, params, fallback_texto
    )


def enviar_instalacao_confirmada(
    telefone: str,
    data_agendamento: Any,
    periodo: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    params = body_params_instalacao_confirmada(data_agendamento, periodo)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_INSTALACAO_CONFIRMADA, params, fallback_texto
    )


def enviar_template_fatura(
    telefone: str,
    template_name: str,
    nome_cliente: str,
    fatura: Any,
    *,
    fallback_texto: str,
    incluir_dias_atraso: bool = False,
) -> Tuple[bool, Any, str]:
    dias = None
    if incluir_dias_atraso:
        dias = int(getattr(fatura, "dias_atraso", 0) or 0)
        if dias <= 0 and getattr(fatura, "data_vencimento", None):
            hoje = timezone.localdate()
            dias = max(0, (hoje - fatura.data_vencimento).days)
    params = body_params_fatura(
        nome_cliente,
        referencia_fatura(fatura),
        getattr(fatura, "valor", 0),
        getattr(fatura, "data_vencimento", None),
        dias_atraso=dias,
    )
    return tentar_enviar_ou_texto(telefone, template_name, params, fallback_texto)


def enviar_pendencia_reagendamento(
    telefone: str,
    nome_cliente: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    """Template Meta de pendência; fallback = texto livre da esteira."""
    params = body_params_pendencia_reagendamento(nome_cliente)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_PENDENCIA_REAGENDAMENTO, params, fallback_texto
    )


def enviar_boas_vindas(
    telefone: str,
    nome_cliente: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    """Template Meta nio_boas_vindas_v1; fallback = texto livre legado."""
    params = body_params_boas_vindas(nome_cliente)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_BOAS_VINDAS, params, fallback_texto
    )
