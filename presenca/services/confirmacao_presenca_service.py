"""
Serviço de confirmação de presença do dia (selfie): registro no banco e envio
da imagem por WhatsApp para a Diretoria.

Centraliza a regra de negócio: um supervisor/diretoria confirma o dia com uma
foto; a imagem é enviada aos diretores com WhatsApp cadastrado (sem armazenamento
externo de arquivo).
"""
from __future__ import annotations

import base64
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from presenca.models import ConfirmacaoPresencaDia
from usuarios.models import Usuario

logger = logging.getLogger(__name__)


class ConfirmacaoPresencaServiceError(Exception):
    """Erro no serviço de confirmação de presença do dia."""

    pass


def usuario_pode_confirmar_presenca(user: Any) -> bool:
    """
    Retorna True se o usuário pode registrar confirmação de presença (selfie):
    superuser, grupos Diretoria/Admin/BackOffice ou supervisor (tem liderados).
    """
    if getattr(user, "is_superuser", False):
        return True
    if user.groups.filter(name__in=["Diretoria", "Admin", "BackOffice"]).exists():
        return True
    if getattr(user, "vendedor_solo", False):
        return True
    if hasattr(user, "liderados") and user.liderados.exists():
        return True
    return False


def obter_confirmacao_dia(
    data_dia: date, user: Any
) -> dict[str, Any]:
    """
    Retorna o payload para o GET: se o usuário é Diretoria/Admin/BackOffice
    vê todas as confirmações do dia; caso contrário apenas as do próprio supervisor.
    """
    from presenca.models import ConfirmacaoPresencaDia
    from presenca.serializers import ConfirmacaoPresencaDiaSerializer

    qs = ConfirmacaoPresencaDia.objects.filter(data=data_dia)
    if not (
        user.is_superuser
        or user.groups.filter(name__in=["Diretoria", "Admin", "BackOffice"]).exists()
    ):
        qs = qs.filter(supervisor=user)
    conf = qs.first()
    if not conf:
        return {"confirmado": False, "detalhe": None}
    return {
        "confirmado": True,
        "detalhe": ConfirmacaoPresencaDiaSerializer(conf).data,
    }


def _normalizar_coordenada(
    valor: Any,
) -> Optional[Decimal]:
    """Converte valor de latitude/longitude para Decimal ou None."""
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _enviar_selfie_diretoria(
    foto_bytes: bytes,
    data_dia: date,
    usuario: Any,
) -> int:
    """
    Envia a selfie por WhatsApp para diretores ativos com telefone cadastrado.
    Retorna a quantidade de envios bem-sucedidos.
    """
    diretores = Usuario.objects.filter(
        groups__name="Diretoria",
        is_active=True,
    ).exclude(tel_whatsapp__isnull=True).exclude(tel_whatsapp="").distinct()

    if not diretores.exists():
        logger.warning(
            "Presença selfie: nenhum diretor com WhatsApp cadastrado (data=%s, supervisor=%s)",
            data_dia,
            getattr(usuario, "username", ""),
        )
        return 0

    from crm_app.whatsapp_service import WhatsAppService

    svc = WhatsAppService()
    data_fmt = data_dia.strftime("%d/%m/%Y")
    caption = f"Presença do dia {data_fmt} - supervisor: {getattr(usuario, 'username', '')}"
    img_b64 = base64.b64encode(foto_bytes).decode("utf-8")
    enviados = 0

    for diretor in diretores:
        tel = (
            (diretor.tel_whatsapp or "")
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if not tel:
            continue
        try:
            resultado = svc.enviar_imagem_b64(tel, img_b64, caption=caption)
            if resultado:
                enviados += 1
            else:
                logger.warning(
                    "Presença selfie: WhatsApp não confirmou envio para %s",
                    diretor.username,
                )
        except Exception as exc:
            logger.warning(
                "Presença selfie: falha ao enviar WhatsApp para %s: %s",
                diretor.username,
                exc,
            )

    logger.info(
        "Presença selfie: %s/%s diretores notificados (data=%s, supervisor=%s)",
        enviados,
        diretores.count(),
        data_dia,
        getattr(usuario, "username", ""),
    )
    return enviados


def registrar_selfie(
    usuario: Any,
    data_dia: date,
    foto_bytes: bytes,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> tuple[ConfirmacaoPresencaDia, bool]:
    """
    Persiste a confirmação do dia e envia a selfie por WhatsApp para a Diretoria.

    Returns:
        Tupla (instância ConfirmacaoPresencaDia, created: bool).
    """
    lat_dec = _normalizar_coordenada(latitude) if latitude is not None else None
    lng_dec = _normalizar_coordenada(longitude) if longitude is not None else None

    conf, created = ConfirmacaoPresencaDia.objects.update_or_create(
        data=data_dia,
        supervisor=usuario,
        defaults={
            "foto_url": "",
            "latitude": lat_dec,
            "longitude": lng_dec,
        },
    )

    _enviar_selfie_diretoria(foto_bytes, data_dia, usuario)

    return conf, created


def excluir_confirmacao_dia(data_dia: date) -> int:
    """
    Remove todas as confirmações (selfies) do dia. Usado pelo DELETE da API.
    Retorna o número de registros excluídos.
    """
    from presenca.models import ConfirmacaoPresencaDia

    deleted, _ = ConfirmacaoPresencaDia.objects.filter(data=data_dia).delete()
    return deleted
