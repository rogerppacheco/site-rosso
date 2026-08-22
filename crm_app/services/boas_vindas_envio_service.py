"""Envio e agendamento de boas-vindas (template Meta + fila)."""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


def _normalizar_telefone_chave(telefone: str) -> str:
    if not telefone:
        return ""
    tel = re.sub(r"\D", "", str(telefone))
    if tel.startswith("55") and len(tel) > 12:
        tel = tel[2:]
    return tel


def montar_texto_fallback_boas_vindas(
    nome_cliente: str,
    *,
    especialista: str = "Especialista",
) -> str:
    agora = timezone.localtime()
    saudacao = "boa tarde" if agora.hour >= 12 else "bom dia"
    despedida = "boa tarde!" if agora.hour >= 12 else "bom dia!"
    return (
        f"Olá {saudacao}, {nome_cliente} tudo bem?\n\n"
        f"Me chamo {especialista}, sou especialista de qualidade do Record PAP, "
        "parceiro Oficial da Nio Fibra.\n\n"
        "Estou entrando em contato para informar que estamos à sua disposição, "
        "caso você precise tirar dúvidas sobre seu plano e faturas.\n\n"
        "Sua primeira fatura irá vencer 25 dias após a instalação.\n\n"
        "Você também pode acompanhar sua conta através do app Nio.\n"
        "Instale o aplicativo no seu aparelho celular.\n\n"
        "Disponível para Android e iOS:\n"
        "Google Play Store (Android)\n"
        "https://play.google.com/store/apps/details?id=br.com.niointernet.app\n\n"
        "Apple Store (iOS):\n"
        "https://apps.apple.com/br/app/nio-internet/id6746278488\n\n"
        "Você ainda pode realizar contato pelos canais de comunicação oficiais da Nio:\n"
        "SAC:0800 001 1000\n"
        "WhatsApp: 21-3605-1000\n\n"
        f"Obrigado e tenha um {despedida}"
    )


def enviar_boas_vindas_venda(
    venda,
    *,
    usuario=None,
    especialista: Optional[str] = None,
) -> dict[str, Any]:
    """
    Envia template Meta nio_boas_vindas_v1 (fallback texto).
    Marca venda + BoasVindasEnviado em sucesso.
    """
    from crm_app.models import BoasVindasEnviado
    from crm_app.services.whatsapp.nio_templates import enviar_boas_vindas

    resultado: dict[str, Any] = {
        "ok": False,
        "enviado": False,
        "detail": "",
        "canal": "",
    }
    telefone = (getattr(venda, "telefone1", None) or "").strip()
    if not telefone:
        resultado["detail"] = "Telefone do cliente não informado."
        return resultado

    if getattr(venda, "boas_vindas_enviado_em", None):
        resultado["ok"] = True
        resultado["detail"] = "Boas-vindas já enviadas anteriormente."
        return resultado

    nome = ""
    if getattr(venda, "cliente", None):
        nome = (venda.cliente.nome_razao_social or "").strip()
    nome = nome or "Cliente"

    esp = (especialista or "").strip()
    if not esp and usuario is not None:
        esp = (
            (getattr(usuario, "first_name", None) or "")
            or (getattr(usuario, "username", None) or "")
        ).strip().split()[0]
    esp = esp or "Especialista"

    fallback = montar_texto_fallback_boas_vindas(nome, especialista=esp)
    try:
        ok, _resp, canal = enviar_boas_vindas(telefone, nome, fallback)
    except Exception as exc:
        logger.exception("[BoasVindas] Erro envio venda=%s", getattr(venda, "id", "?"))
        resultado["detail"] = str(exc)[:300]
        return resultado

    if not ok:
        resultado["detail"] = "Falha ao enviar WhatsApp (API)."
        return resultado

    venda.boas_vindas_enviado_em = timezone.now()
    venda.save(update_fields=["boas_vindas_enviado_em"])
    tel_chave = _normalizar_telefone_chave(telefone)
    if tel_chave:
        BoasVindasEnviado.objects.create(telefone=tel_chave, venda=venda)

    resultado.update(
        {
            "ok": True,
            "enviado": True,
            "canal": canal,
            "detail": f"Enviado via {canal}.",
        }
    )
    return resultado


def agendar_boas_vindas_venda(
    venda,
    *,
    usuario=None,
    delay_minutos: Optional[int] = None,
) -> dict[str, Any]:
    """
    Coloca a venda na fila (anti-spam). Se já enviou ou já está na fila, no-op.
    """
    from crm_app.models import FilaEnvioBoasVindas

    resultado: dict[str, Any] = {"ok": True, "agendado": False, "detail": ""}
    if not venda:
        resultado["ok"] = False
        resultado["detail"] = "Venda inválida."
        return resultado

    if getattr(venda, "boas_vindas_enviado_em", None):
        resultado["detail"] = "Já enviado."
        return resultado

    telefone = (getattr(venda, "telefone1", None) or "").strip()
    if not telefone:
        resultado["ok"] = False
        resultado["detail"] = "Sem telefone."
        return resultado

    if FilaEnvioBoasVindas.objects.filter(
        venda=venda, enviado_em__isnull=True
    ).exists():
        resultado["detail"] = "Já na fila."
        return resultado

    data_inst = getattr(venda, "data_instalacao", None) or timezone.localdate()
    delay = delay_minutos if delay_minutos is not None else random.randint(2, 8)
    agendado_para = timezone.now() + timedelta(minutes=max(1, delay))

    FilaEnvioBoasVindas.objects.create(
        venda=venda,
        data_instalacao=data_inst,
        agendado_para=agendado_para,
        criado_por=usuario if getattr(usuario, "is_authenticated", False) else None,
    )
    resultado["agendado"] = True
    resultado["detail"] = f"Agendado para {agendado_para.strftime('%d/%m %H:%M')}."
    logger.info(
        "[BoasVindas] Agendado venda=%s para %s",
        venda.id,
        agendado_para.isoformat(),
    )
    return resultado


def tentar_agendar_ao_instalar(
    venda,
    *,
    usuario=None,
    enviar: bool = True,
) -> dict[str, Any]:
    """Hook da esteira: ao virar INSTALADA, agenda se ``enviar``."""
    if not enviar:
        return {"ok": True, "agendado": False, "detail": "Envio desmarcado pelo usuário."}
    status = getattr(venda, "status_esteira", None)
    nome = (getattr(status, "nome", "") or "").upper()
    if "INSTALADA" not in nome or "CANCEL" in nome:
        return {"ok": True, "agendado": False, "detail": "Status não é INSTALADA."}
    return agendar_boas_vindas_venda(venda, usuario=usuario)
