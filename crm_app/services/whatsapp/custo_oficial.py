"""
Estimativa e registro de custo de mensagens do Número B (oficial / cliente).

Tarifas padrão BR (lista Meta / BRL, utility e marketing) são configuráveis
no model WhatsAppTarifaOficial. Texto livre na janela de serviço = R$ 0,00.
Templates UTILITY fora da janela 24h = tarifa utility.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Count, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

# Lista Meta BR (referência Jul/2026) — ajustável no admin sem deploy
DEFAULT_UTILITY_BRL = Decimal("0.0350")
DEFAULT_MARKETING_BRL = Decimal("0.3217")
DEFAULT_AUTH_BRL = Decimal("0.0350")
DEFAULT_SERVICE_BRL = Decimal("0.0000")

CATEGORIA_UTILITY = "UTILITY"
CATEGORIA_MARKETING = "MARKETING"
CATEGORIA_AUTHENTICATION = "AUTHENTICATION"
CATEGORIA_SERVICE = "SERVICE"

TIPO_TEMPLATE = "TEMPLATE"
TIPO_TEXTO = "TEXTO"
TIPO_BOTOES = "BOTOES"
TIPO_MIDIA = "MIDIA"


def _dec(valor: Any) -> Decimal:
    try:
        return Decimal(str(valor))
    except Exception:
        return Decimal("0")


def obter_tarifas() -> dict[str, Decimal]:
    """Lê tarifas do singleton; cria com defaults se não existir."""
    from crm_app.models import WhatsAppTarifaOficial

    obj, _ = WhatsAppTarifaOficial.objects.get_or_create(
        pk=1,
        defaults={
            "utility_brl": DEFAULT_UTILITY_BRL,
            "marketing_brl": DEFAULT_MARKETING_BRL,
            "authentication_brl": DEFAULT_AUTH_BRL,
            "service_brl": DEFAULT_SERVICE_BRL,
            "observacao": (
                "Tarifas lista Meta BR (BRL). Utility/Auth têm desconto por volume; "
                "ajuste no admin se a fatura Meta divergir."
            ),
        },
    )
    return {
        CATEGORIA_UTILITY: _dec(obj.utility_brl),
        CATEGORIA_MARKETING: _dec(obj.marketing_brl),
        CATEGORIA_AUTHENTICATION: _dec(obj.authentication_brl),
        CATEGORIA_SERVICE: _dec(obj.service_brl),
    }


def classificar_envio(
    *,
    tipo_envio: str,
    template_name: Optional[str] = None,
) -> str:
    """Infere categoria de cobrança Meta a partir do tipo/template."""
    tipo = (tipo_envio or "").strip().upper()
    nome = (template_name or "").strip().lower()
    if tipo == TIPO_TEMPLATE or nome:
        if "marketing" in nome or nome.startswith("mkt_"):
            return CATEGORIA_MARKETING
        if "auth" in nome or "otp" in nome:
            return CATEGORIA_AUTHENTICATION
        # Templates Nio (confirmação, instalação, fatura, pendência, boas-vindas) = UTILITY
        return CATEGORIA_UTILITY
    # Texto/botões/mídia: janela de serviço (custo 0 na regra atual)
    return CATEGORIA_SERVICE


def estimar_custo(
    *,
    tipo_envio: str,
    template_name: Optional[str] = None,
    sucesso: bool = True,
) -> tuple[Decimal, str]:
    if not sucesso:
        return Decimal("0.0000"), classificar_envio(
            tipo_envio=tipo_envio, template_name=template_name
        )
    categoria = classificar_envio(tipo_envio=tipo_envio, template_name=template_name)
    tarifas = obter_tarifas()
    return tarifas.get(categoria, Decimal("0")), categoria


def _extrair_message_id(resp: Any) -> str:
    if not isinstance(resp, dict):
        return ""
    for key in ("messageId", "message_id", "id", "wamid"):
        val = resp.get(key)
        if val:
            return str(val)[:120]
    data = resp.get("data")
    if isinstance(data, dict):
        for key in ("messageId", "id", "wamid"):
            val = data.get(key)
            if val:
                return str(val)[:120]
    return ""


def registrar_envio_oficial(
    *,
    telefone: str,
    tipo_envio: str,
    sucesso: bool,
    resposta: Any = None,
    template_name: str = "",
    origem: str = "",
    erro: str = "",
) -> None:
    """Persiste histórico + custo estimado (não bloqueia o fluxo de envio)."""
    try:
        from crm_app.models import HistoricoCustoWhatsAppOficial

        custo, categoria = estimar_custo(
            tipo_envio=tipo_envio,
            template_name=template_name,
            sucesso=sucesso,
        )
        HistoricoCustoWhatsAppOficial.objects.create(
            telefone=(telefone or "")[:30],
            tipo_envio=(tipo_envio or TIPO_TEXTO)[:20],
            template_name=(template_name or "")[:120],
            categoria=categoria,
            custo_estimado_brl=custo,
            sucesso=bool(sucesso),
            message_id=_extrair_message_id(resposta),
            origem=(origem or "")[:60],
            erro=(erro or str(resposta) if not sucesso and resposta else "")[:500],
        )
    except Exception:
        logger.exception("[CustoWA] Falha ao registrar histórico de custo")


def resumo_custos() -> dict[str, Any]:
    """Totais para dashboard (gasto acumulado + mês corrente)."""
    from crm_app.models import HistoricoCustoWhatsAppOficial

    qs = HistoricoCustoWhatsAppOficial.objects.filter(sucesso=True)
    agg = qs.aggregate(total=Sum("custo_estimado_brl"), qtd=Count("id"))
    inicio_mes = timezone.localtime().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    mes = qs.filter(criado_em__gte=inicio_mes).aggregate(
        total=Sum("custo_estimado_brl"), qtd=Count("id")
    )
    hoje_ini = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    hoje = qs.filter(criado_em__gte=hoje_ini).aggregate(
        total=Sum("custo_estimado_brl"), qtd=Count("id")
    )
    tarifas = obter_tarifas()
    recentes = list(
        HistoricoCustoWhatsAppOficial.objects.order_by("-criado_em")[:30].values(
            "id",
            "telefone",
            "tipo_envio",
            "template_name",
            "categoria",
            "custo_estimado_brl",
            "sucesso",
            "origem",
            "criado_em",
        )
    )
    for row in recentes:
        row["custo_estimado_brl"] = str(row["custo_estimado_brl"])
        if row.get("criado_em"):
            row["criado_em"] = row["criado_em"].isoformat()
    return {
        "moeda": "BRL",
        "tarifas": {k: str(v) for k, v in tarifas.items()},
        "total_gasto_brl": str(agg["total"] or Decimal("0")),
        "total_mensagens": int(agg["qtd"] or 0),
        "mes_gasto_brl": str(mes["total"] or Decimal("0")),
        "mes_mensagens": int(mes["qtd"] or 0),
        "hoje_gasto_brl": str(hoje["total"] or Decimal("0")),
        "hoje_mensagens": int(hoje["qtd"] or 0),
        "custo_por_msg_utility_brl": str(tarifas[CATEGORIA_UTILITY]),
        "recentes": recentes,
        "nota": (
            "Estimativa com tarifas configuráveis. Meta pode isentar utility "
            "dentro da janela 24h; texto livre = serviço (R$ 0)."
        ),
    }
