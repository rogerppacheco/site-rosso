"""
Serviço de reemissão de venda (duplicação para nova OS/agendamento).

Centraliza a regra de negócio: copiar uma venda existente para uma nova ordem de serviço,
preservando data_criacao e demais dados, alterando apenas OS, data de abertura, agendamento,
status esteira (AGENDADO) e flag de reemissão. Opcionalmente dispara notificação WhatsApp
ao vendedor para não duplicar lógica entre views e jobs.
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from crm_app.models import StatusCRM, Venda

logger = logging.getLogger(__name__)


class ReemissaoVendaError(Exception):
    """Erro de regra de negócio na reemissão (ex.: status AGENDADO inexistente)."""

    pass


def duplicar(
    id_venda: int,
    nova_os: str,
    nova_data: Any,
    novo_turno: str,
    enviar_whatsapp: bool = True,
) -> Venda:
    """
    Cria uma nova venda (reemissão) a partir da venda original.

    A reemissão mantém todos os dados da venda original (incluindo data_criacao)
    para não alterar métricas de origem. Apenas os campos ligados à nova OS e
    ao agendamento são sobrescritos, e o status esteira é fixado em AGENDADO
    para refletir que a venda voltou à fila de instalação.

    Args:
        id_venda: PK da venda a duplicar.
        nova_os: Número da nova ordem de serviço.
        nova_data: Data do novo agendamento (date ou string ISO).
        novo_turno: Período do agendamento (ex.: MANHA, TARDE).
        enviar_whatsapp: Se True, envia mensagem de aprovação ao tel_whatsapp do vendedor.

    Returns:
        Instância da nova Venda já persistida (com data_criacao preservada).

    Raises:
        Venda.DoesNotExist: Quando id_venda não existe.
        ReemissaoVendaError: Quando o status "AGENDADO" (Esteira) não existe no cadastro.
    """
    venda_original = Venda.objects.get(id=id_venda)

    venda_nova = Venda()
    data_criacao_original = venda_original.data_criacao

    for field in venda_original._meta.get_fields():
        if field.auto_created or field.name in ("id", "pk"):
            continue
        if hasattr(venda_original, field.name):
            value = getattr(venda_original, field.name)
            setattr(venda_nova, field.name, value)

    venda_nova.ordem_servico = nova_os
    venda_nova.data_abertura = timezone.now()
    venda_nova.data_agendamento = nova_data
    venda_nova.periodo_agendamento = novo_turno
    venda_nova.reemissao = True

    # Reemissão = nova OS; não herda adiantamento sábado / antecipação da venda original.
    venda_nova.adiantamento_sabado_marcado = False
    venda_nova.adiantamento_sabado_valor = None
    venda_nova.adiantamento_sabado_valor_pago = None
    venda_nova.adiantamento_sabado_marcado_em = None
    venda_nova.adiantamento_sabado_marcado_por = None
    venda_nova.adiantamento_sabado_manual = False
    venda_nova.adiantamento_sabado_obs_manual = ''
    venda_nova.adiantamento_sabado_quitado_em = None
    venda_nova.flag_desc_adiantamento_sabado = False
    venda_nova.antecipacao_comissao = False

    status_agendado = StatusCRM.objects.filter(
        nome__iexact="AGENDADO", tipo__iexact="Esteira"
    ).first()
    if not status_agendado:
        raise ReemissaoVendaError("Status AGENDADO (Esteira) não encontrado.")
    venda_nova.status_esteira = status_agendado

    venda_nova.save()

    if data_criacao_original:
        Venda.objects.filter(id=venda_nova.id).update(
            data_criacao=data_criacao_original
        )
        venda_nova.data_criacao = data_criacao_original

    telefone_vendedor = (
        getattr(venda_nova.vendedor, "tel_whatsapp", None) if venda_nova.vendedor else None
    )
    if enviar_whatsapp and telefone_vendedor:
        try:
            from crm_app.whatsapp_service import WhatsAppService

            WhatsAppService().enviar_mensagem_cadastrada(
                venda_nova, telefone_destino=telefone_vendedor
            )
        except Exception as e:
            logger.warning("Erro ao enviar WhatsApp para reemissão: %s", e)

    return venda_nova
