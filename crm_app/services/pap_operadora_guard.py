"""
Bloqueio das automações do PAP Nio conforme a operadora.

O PAP é o portal do parceiro da NIO: abrir uma sessão lá para um pedido de outra
operadora (Vero, Velox) consome BO do pool, ocupa o worker Playwright e nunca
encontra o pedido. O cadastro de Operadora passa a ser a fonte da verdade pelo
campo ``usa_pap_nio``.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Tuple

from django.db.models import Q

logger = logging.getLogger(__name__)

NOME_OPERADORA_PAP = "NIO"

MSG_OPERADORA_SEM_PAP = (
    "🚫 *Automação indisponível para esta operadora*\n\n"
    "O pedido é da operadora *{operadora}*, que não utiliza o PAP Nio.\n"
    "Consulte o status diretamente no portal da operadora."
)

MSG_PAP_DESATIVADO = (
    "🚫 *Automações do PAP Nio desativadas*\n\n"
    "A operadora NIO está com o PAP desligado no cadastro.\n"
    "Procure a supervisão para liberar."
)


def pap_nio_habilitado() -> bool:
    """
    Diz se a operadora NIO está cadastrada e com o PAP liberado.

    Usado nos fluxos que ainda não têm pedido (CRÉDITO e VENDER) e como regra de
    fallback quando o documento consultado não tem venda no CRM. Em caso de erro
    de banco falha aberto, para não derrubar a venda por indisponibilidade.
    """
    from crm_app.models import Operadora

    try:
        return Operadora.objects.filter(
            nome__iexact=NOME_OPERADORA_PAP,
            usa_pap_nio=True,
        ).exists()
    except Exception:
        logger.exception("[PAP_GUARD] Falha ao consultar a operadora %s.", NOME_OPERADORA_PAP)
        return True


def operadora_da_venda(venda: Any) -> Optional[Any]:
    plano = getattr(venda, "plano", None)
    return getattr(plano, "operadora", None) if plano else None


def venda_liberada_para_pap(venda: Any) -> Tuple[bool, str]:
    """
    Avalia uma venda concreta e devolve ``(liberado, mensagem_de_bloqueio)``.

    Venda sem plano ou sem operadora não permite provar que é NIO, então cai na
    regra global do cadastro.
    """
    operadora = operadora_da_venda(venda)
    if operadora is None:
        return (True, "") if pap_nio_habilitado() else (False, MSG_PAP_DESATIVADO)
    if getattr(operadora, "usa_pap_nio", False):
        return True, ""
    return False, MSG_OPERADORA_SEM_PAP.format(operadora=operadora.nome)


def bloqueio_por_documento(documento: str, ordem_servico: str = "") -> str:
    """
    Devolve a mensagem de bloqueio para um CPF/CNPJ, ou string vazia se liberado.

    Quando a O.S é conhecida ela tem prioridade, por identificar o pedido exato;
    caso contrário usa a venda ativa mais recente do documento. Sem venda,
    aplica a regra global do cadastro.
    """
    doc = re.sub(r"\D", "", documento or "")
    os_limpa = (ordem_servico or "").strip()
    if not doc and not os_limpa:
        return "" if pap_nio_habilitado() else MSG_PAP_DESATIVADO

    from crm_app.models import Venda

    try:
        base = Venda.objects.filter(ativo=True).select_related("plano__operadora")
        venda = base.filter(ordem_servico=os_limpa).first() if os_limpa else None
        if venda is None and doc:
            venda = (
                base.filter(cliente__cpf_cnpj__icontains=doc)
                .order_by("-data_criacao")
                .first()
            )
    except Exception:
        logger.exception("[PAP_GUARD] Falha ao localizar venda do documento informado.")
        return ""

    if venda is None:
        return "" if pap_nio_habilitado() else MSG_PAP_DESATIVADO

    liberado, motivo = venda_liberada_para_pap(venda)
    if not liberado:
        logger.info(
            "[PAP_GUARD] PAP bloqueado para venda %s (operadora sem PAP Nio).", venda.pk
        )
    return "" if liberado else motivo


def filtro_vendas_com_pap() -> Q:
    """Filtro de queryset para varreduras em lote (sincronização noturna)."""
    return Q(plano__operadora__usa_pap_nio=True)
