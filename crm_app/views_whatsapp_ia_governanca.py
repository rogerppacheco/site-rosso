"""APIs de gestão da IA WhatsApp (Governança)."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from crm_app.models import WhatsAppTelefoneSemIa
from crm_app.services.whatsapp_ia_config_service import (
    atualizar_whatsapp_ia_config,
    serializar_whatsapp_ia_config,
)
from crm_app.whatsapp_telefone_blocklist import normalizar_telefone_blocklist


def _serializar_telefone(item: WhatsAppTelefoneSemIa) -> dict:
    return {
        "id": item.id,
        "telefone": item.telefone,
        "descricao": item.descricao,
        "motivo": item.motivo,
        "motivo_label": item.get_motivo_display(),
        "ativo": item.ativo,
        "criado_em": item.criado_em,
        "atualizado_em": item.atualizado_em,
        "criado_por": item.criado_por.username if item.criado_por else None,
    }


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def whatsapp_ia_config_view(request):
    """Retorna ou atualiza toggles globais da IA no WhatsApp."""
    if request.method == "GET":
        telefones = WhatsAppTelefoneSemIa.objects.select_related("criado_por").order_by("-criado_em")
        return Response(
            {
                "config": serializar_whatsapp_ia_config(),
                "telefones_sem_ia": [_serializar_telefone(t) for t in telefones],
            }
        )

    cfg = atualizar_whatsapp_ia_config(request.data or {}, request.user)
    return Response({"config": serializar_whatsapp_ia_config(cfg)})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def whatsapp_telefones_sem_ia_view(request):
    """Lista ou cadastra números bloqueados (sem interação da IA/bot)."""
    if request.method == "GET":
        qs = WhatsAppTelefoneSemIa.objects.select_related("criado_por").order_by("-criado_em")
        return Response([_serializar_telefone(t) for t in qs])

    telefone_raw = (request.data.get("telefone") or "").strip()
    telefone = normalizar_telefone_blocklist(telefone_raw)
    if len(telefone) < 10:
        return Response(
            {"detail": "Informe um telefone válido (mínimo 10 dígitos)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    motivo = (request.data.get("motivo") or WhatsAppTelefoneSemIa.MOTIVO_CONVERSA_MANUAL).strip()
    motivos_validos = {c[0] for c in WhatsAppTelefoneSemIa.MOTIVO_CHOICES}
    if motivo not in motivos_validos:
        motivo = WhatsAppTelefoneSemIa.MOTIVO_CONVERSA_MANUAL

    descricao = (request.data.get("descricao") or "").strip()[:200]

    existente = WhatsAppTelefoneSemIa.objects.filter(telefone=telefone).first()
    if existente:
        existente.descricao = descricao or existente.descricao
        existente.motivo = motivo
        existente.ativo = True
        existente.save(update_fields=["descricao", "motivo", "ativo", "atualizado_em"])
        return Response(_serializar_telefone(existente))

    item = WhatsAppTelefoneSemIa.objects.create(
        telefone=telefone,
        descricao=descricao,
        motivo=motivo,
        criado_por=request.user,
    )
    return Response(_serializar_telefone(item), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def whatsapp_telefone_sem_ia_detail_view(request, pk: int):
    """Atualiza ou remove um número da blocklist."""
    try:
        item = WhatsAppTelefoneSemIa.objects.get(pk=pk)
    except WhatsAppTelefoneSemIa.DoesNotExist:
        return Response({"detail": "Registro não encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if "ativo" in request.data:
        item.ativo = bool(request.data["ativo"])
    if "descricao" in request.data:
        item.descricao = str(request.data["descricao"] or "").strip()[:200]
    if "motivo" in request.data:
        motivo = str(request.data["motivo"] or "").strip()
        motivos_validos = {c[0] for c in WhatsAppTelefoneSemIa.MOTIVO_CHOICES}
        if motivo in motivos_validos:
            item.motivo = motivo
    item.save()
    return Response(_serializar_telefone(item))
