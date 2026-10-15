"""Inbox de atendimento WhatsApp no número do cliente (Cloud API).

Persiste entradas do webhook oficial e saídas do CRM (texto de sessão e modelos).
A resposta do operador só segue com a janela de 24 horas aberta.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any, Iterator, Optional

from django.db import IntegrityError, transaction
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

logger = logging.getLogger(__name__)

JANELA_ATENDIMENTO = timedelta(hours=24)

AVISO_JANELA_FECHADA = (
    "A janela de 24 horas da Meta está fechada. "
    "Texto livre pela Cloud API só pode ser enviado se a última mensagem do cliente "
    "tiver chegado há menos de 24 horas. "
    "Fora dessa janela, somente um modelo aprovado pode reabrir a conversa. "
    "O envio de modelo não está disponível nesta tela."
)

AVISO_SEM_MENSAGEM_CLIENTE = (
    "Ainda não há mensagem recebida deste contato. "
    "A Cloud API só libera texto livre depois que o cliente escreve, e apenas por 24 horas. "
    "Fora dessa janela, somente um modelo aprovado pode reabrir a conversa. "
    "O envio de modelo não está disponível nesta tela."
)

AVISO_CANAL_INDISPONIVEL = (
    "O número oficial ainda não está liberado para envio a clientes. "
    "Quando a Meta aprovar o número e os envios a clientes forem ativados na aba WPP, "
    "esta tela passa a enviar normalmente."
)

_BACKENDS_OFICIAIS = frozenset({"meta", "whatsatende"})

_ctx_saida: ContextVar[Optional[dict]] = ContextVar("wa_atendimento_saida", default=None)


@contextmanager
def contexto_registro_saida(**kwargs: Any) -> Iterator[None]:
    """Marca a próxima saída do número do cliente (operador, pedido, origem)."""
    token = _ctx_saida.set(kwargs)
    try:
        yield
    finally:
        _ctx_saida.reset(token)


def _ctx() -> dict:
    return _ctx_saida.get() or {}


def canonicalizar_telefone(telefone: str) -> str:
    from crm_app.whatsapp_telefone_blocklist import normalizar_telefone_blocklist

    return normalizar_telefone_blocklist(telefone or "")


def telefones_equivalentes(telefone: str) -> list[str]:
    from crm_app.whatsapp_webhook_handler import _chaves_telefone_variantes

    canon = canonicalizar_telefone(telefone)
    chaves = list(_chaves_telefone_variantes(telefone) or [])
    if canon and canon not in chaves:
        chaves.append(canon)
    return [c for c in chaves if c]


def exibir_telefone(telefone: str) -> str:
    digitos = canonicalizar_telefone(telefone)
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return digitos or (telefone or "")


def _extrair_message_id(resposta: Any) -> str:
    if not isinstance(resposta, dict):
        return ""
    for chave in ("messageId", "message_id", "id", "wamid"):
        valor = resposta.get(chave)
        if valor:
            return str(valor)[:128]
    msgs = resposta.get("messages")
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
        mid = msgs[0].get("id")
        if mid:
            return str(mid)[:128]
    return ""


def _erro_resposta(resposta: Any, sucesso: bool) -> str:
    if sucesso or resposta is None:
        return ""
    if isinstance(resposta, str):
        return resposta[:500]
    if isinstance(resposta, dict):
        erro = resposta.get("error")
        if isinstance(erro, dict):
            return str(erro.get("message") or erro)[:500]
        if erro:
            return str(erro)[:500]
        return str(resposta)[:500]
    return str(resposta)[:500]


def resolver_venda(telefone: str):
    try:
        from crm_app.cliente_atendimento_ia_service import (
            buscar_venda_ativa_por_telefone_cliente,
        )

        return buscar_venda_ativa_por_telefone_cliente(telefone)
    except Exception:
        logger.debug("[Atendimento WA] Falha ao localizar pedido", exc_info=True)
        return None


def _venda_do_contexto_ou_telefone(telefone: str):
    ctx = _ctx()
    venda = ctx.get("venda")
    if venda is not None:
        return venda
    venda_id = ctx.get("venda_id")
    if venda_id:
        from crm_app.models import Venda

        return Venda.objects.filter(pk=venda_id).first()
    return resolver_venda(telefone)


def gravar_mensagem(
    *,
    telefone: str,
    direcao: str,
    texto: str,
    tipo: str,
    origem: str,
    sucesso: bool = True,
    message_id: str = "",
    template_name: str = "",
    erro: str = "",
    venda=None,
    enviado_por=None,
    data_hora=None,
):
    """Cria o registro. Mensagens com o mesmo id e direção não duplicam."""
    from crm_app.models import MensagemWhatsAppAtendimento

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return None
    texto_limpo = (texto or "")[:8000]
    mid = (message_id or "")[:128]
    if venda is None:
        venda = _venda_do_contexto_ou_telefone(tel)

    campos = dict(
        telefone=tel,
        venda=venda,
        direcao=direcao,
        tipo=tipo or MensagemWhatsAppAtendimento.TIPO_SESSAO,
        texto=texto_limpo,
        template_name=(template_name or "")[:120],
        message_id=mid,
        origem=(origem or "")[:20],
        sucesso=bool(sucesso),
        erro=(erro or "")[:2000],
        enviado_por=enviado_por,
    )
    if data_hora is not None:
        campos["data_hora"] = data_hora

    if mid:
        existente = MensagemWhatsAppAtendimento.objects.filter(
            message_id=mid,
            direcao=direcao,
        ).first()
        if existente:
            return existente

    try:
        with transaction.atomic():
            return MensagemWhatsAppAtendimento.objects.create(**campos)
    except IntegrityError:
        if mid:
            return MensagemWhatsAppAtendimento.objects.filter(
                message_id=mid,
                direcao=direcao,
            ).first()
        raise


def _texto_entrada(data: dict) -> str:
    texto = ""
    bloco = data.get("text")
    if isinstance(bloco, dict):
        texto = bloco.get("message") or bloco.get("text") or bloco.get("body") or ""
    if not texto:
        msg = data.get("message")
        if isinstance(msg, dict):
            texto = msg.get("text") or msg.get("body") or msg.get("message") or ""
        elif isinstance(msg, str):
            texto = msg
    texto = str(texto or "").strip()
    if texto:
        return texto[:5000]

    tipo = str(data.get("whatsatendeMessageType") or "").lower()
    if isinstance(data.get("image"), dict) or tipo in ("image", "img", "sticker"):
        return "[imagem]"
    if isinstance(data.get("audio"), dict) or tipo in ("audio", "ptt"):
        return "[áudio]"
    if isinstance(data.get("video"), dict) or tipo == "video":
        return "[vídeo]"
    if isinstance(data.get("document"), dict) or tipo in ("document", "pdf", "file"):
        return "[documento]"
    return ""


def _canal_cliente(data: dict) -> bool:
    """Número oficial do cliente: Cloud API Meta ou WhatsAtende (Número B)."""
    return bool(data.get("_meta_raw") is not None or data.get("_whatsatende_raw") is not None)


def registrar_entrada_webhook(data: Any):
    """Grava mensagem do canal do cliente. Ignora o bot interno (Z-API/Evolution)."""
    if not isinstance(data, dict) or not data:
        return None
    payload = data
    if not _canal_cliente(payload):
        bruto = payload.get("object") == "whatsapp_business_account" or payload.get("senderNumber")
        if bruto:
            from crm_app.whatsapp_webhook_normalizer import normalizar_webhook

            payload = normalizar_webhook(payload)
        if not isinstance(payload, dict) or not _canal_cliente(payload):
            return None
    if payload.get("isGroup"):
        return None

    telefone = payload.get("phone") or payload.get("from") or ""
    texto = _texto_entrada(payload)
    if not texto:
        return None

    from crm_app.models import MensagemWhatsAppAtendimento

    from_me = bool(payload.get("fromMe") or payload.get("isFromMe") or payload.get("from_me"))
    direcao = (
        MensagemWhatsAppAtendimento.DIRECAO_SAIDA
        if from_me
        else MensagemWhatsAppAtendimento.DIRECAO_ENTRADA
    )
    origem = (
        MensagemWhatsAppAtendimento.ORIGEM_CANAL
        if from_me
        else MensagemWhatsAppAtendimento.ORIGEM_WEBHOOK
    )
    try:
        return gravar_mensagem(
            telefone=str(telefone),
            direcao=direcao,
            texto=texto,
            tipo=MensagemWhatsAppAtendimento.TIPO_SESSAO,
            origem=origem,
            sucesso=True,
            message_id=str(payload.get("messageId") or "")[:128],
        )
    except Exception:
        logger.exception("[Atendimento WA] Falha ao gravar mensagem do webhook")
        return None


def registrar_saida_cliente(
    *,
    telefone: str,
    texto: str,
    tipo: str,
    sucesso: bool,
    resposta: Any = None,
    template_name: str = "",
) -> None:
    """Chamado pelo WhatsAppService no purpose cliente. Não propaga erro de gravação."""
    from crm_app.models import MensagemWhatsAppAtendimento

    ctx = _ctx()
    origem = ctx.get("origem") or MensagemWhatsAppAtendimento.ORIGEM_CRM
    enviado_por = ctx.get("enviado_por")
    try:
        gravar_mensagem(
            telefone=telefone,
            direcao=MensagemWhatsAppAtendimento.DIRECAO_SAIDA,
            texto=texto or (f"Modelo: {template_name}" if template_name else ""),
            tipo=tipo,
            origem=origem,
            sucesso=sucesso,
            message_id=_extrair_message_id(resposta),
            template_name=template_name,
            erro=_erro_resposta(resposta, sucesso),
            venda=ctx.get("venda"),
            enviado_por=enviado_por,
        )
    except Exception:
        logger.exception("[Atendimento WA] Falha ao gravar saída")


def texto_modelo(template_name: str, body_params: Any = None) -> str:
    linhas = [f"Modelo: {template_name or 'sem nome'}"]
    params = body_params if isinstance(body_params, (list, tuple)) else None
    if params is None and isinstance(body_params, dict):
        corpo = body_params.get("body")
        if isinstance(corpo, list):
            params = corpo
    if params:
        for indice, valor in enumerate(params, start=1):
            linhas.append(f"{{{{{indice}}}}} {valor}")
    return "\n".join(linhas)


def ultima_entrada(telefone: str):
    from crm_app.models import MensagemWhatsAppAtendimento

    chaves = telefones_equivalentes(telefone)
    if not chaves:
        return None
    return (
        MensagemWhatsAppAtendimento.objects.filter(
            telefone__in=chaves,
            direcao=MensagemWhatsAppAtendimento.DIRECAO_ENTRADA,
        )
        .order_by("-data_hora", "-id")
        .first()
    )


def estado_janela(telefone: str, agora=None) -> dict:
    agora = agora or timezone.now()
    ultima = ultima_entrada(telefone)
    if ultima is None:
        return {
            "aberta": False,
            "ate": None,
            "ultima_entrada_em": None,
            "aviso": AVISO_SEM_MENSAGEM_CLIENTE,
        }
    limite = ultima.data_hora + JANELA_ATENDIMENTO
    aberta = (agora - ultima.data_hora) < JANELA_ATENDIMENTO
    return {
        "aberta": aberta,
        "ate": limite if aberta else None,
        "ultima_entrada_em": ultima.data_hora,
        "aviso": "" if aberta else AVISO_JANELA_FECHADA,
    }


def canal_oficial_pronto() -> bool:
    """O inbox só envia pelo número oficial (Cloud API Meta ou WhatsAtende B)."""
    try:
        from crm_app.services.whatsapp.factory import (
            PURPOSE_CLIENTE,
            resolve_backend_for_purpose,
        )
        from crm_app.services.whatsapp_config_service import (
            canal_cliente_pronto,
            get_active_whatsapp_provider_name,
        )

        if not canal_cliente_pronto():
            return False
        backend, role = resolve_backend_for_purpose(
            get_active_whatsapp_provider_name(), PURPOSE_CLIENTE
        )
        return role == PURPOSE_CLIENTE and backend in _BACKENDS_OFICIAIS
    except Exception:
        logger.debug("[Atendimento WA] Falha ao checar canal oficial", exc_info=True)
        return False


def bot_pausado(telefone: str) -> bool:
    from crm_app.whatsapp_telefone_blocklist import telefone_esta_bloqueado

    return telefone_esta_bloqueado(telefone)


def pausar_bot(telefone: str, usuario, descricao: str = "") -> None:
    from crm_app.models import WhatsAppTelefoneSemIa

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 10:
        return
    texto = (descricao or "Conversa assumida no atendimento WhatsApp")[:200]
    item = WhatsAppTelefoneSemIa.objects.filter(telefone=tel).first()
    if item:
        item.ativo = True
        item.motivo = WhatsAppTelefoneSemIa.MOTIVO_CONVERSA_MANUAL
        item.descricao = texto
        if usuario is not None and getattr(usuario, "pk", None) and not item.criado_por_id:
            item.criado_por = usuario
        item.save()
        return
    WhatsAppTelefoneSemIa.objects.create(
        telefone=tel,
        descricao=texto,
        motivo=WhatsAppTelefoneSemIa.MOTIVO_CONVERSA_MANUAL,
        ativo=True,
        criado_por=usuario if getattr(usuario, "pk", None) else None,
    )


def _qs_visivel(usuario) -> QuerySet:
    from crm_app.models import MensagemWhatsAppAtendimento
    from crm_app.services.escopo_operadora import (
        operadora_ids_permitidas,
        usuario_tem_bypass_operadora,
    )

    qs = MensagemWhatsAppAtendimento.objects.all()
    if usuario_tem_bypass_operadora(usuario):
        return qs
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return qs
    return qs.filter(
        Q(venda__isnull=True) | Q(venda__plano__operadora_id__in=permitidas)
    )


def venda_visivel(usuario, venda) -> bool:
    if venda is None:
        return True
    from crm_app.services.escopo_operadora import (
        operadora_ids_permitidas,
        usuario_tem_bypass_operadora,
    )

    if usuario_tem_bypass_operadora(usuario):
        return True
    permitidas = operadora_ids_permitidas(usuario)
    plano = getattr(venda, "plano", None)
    operadora_id = getattr(plano, "operadora_id", None) if plano is not None else None
    if not operadora_id:
        return permitidas is None
    if permitidas is None:
        return True
    return int(operadora_id) in permitidas


def conversa_visivel(usuario, telefone: str) -> bool:
    if not _qs_visivel(usuario).filter(telefone__in=telefones_equivalentes(telefone)).exists():
        return False
    venda = _venda_cabecalho(telefone, usuario)
    return venda_visivel(usuario, venda)


def _venda_cabecalho(telefone: str, usuario=None):
    from crm_app.models import MensagemWhatsAppAtendimento

    chaves = telefones_equivalentes(telefone)
    if not chaves:
        return None
    qs = MensagemWhatsAppAtendimento.objects.filter(telefone__in=chaves, venda__isnull=False)
    if usuario is not None:
        qs = _qs_visivel(usuario).filter(telefone__in=chaves, venda__isnull=False)
    msg = (
        qs.select_related("venda__cliente", "venda__plano")
        .order_by("-data_hora", "-id")
        .first()
    )
    if msg and msg.venda_id:
        return msg.venda
    venda = resolver_venda(canonicalizar_telefone(telefone))
    if usuario is not None and not venda_visivel(usuario, venda):
        return None
    return venda


def _nome_cliente(venda) -> Optional[str]:
    cliente = getattr(venda, "cliente", None) if venda is not None else None
    if cliente is None:
        return None
    return cliente.nome_razao_social or None


def serializar_mensagem(msg) -> dict:
    return {
        "id": msg.id,
        "direcao": msg.direcao,
        "direcao_label": "Recebida" if msg.direcao == "ENTRADA" else "Enviada",
        "tipo": msg.tipo,
        "tipo_label": "Modelo" if msg.tipo == "MODELO" else "Sessão",
        "texto": msg.texto or "",
        "template_name": msg.template_name or "",
        "data_hora": msg.data_hora.isoformat() if msg.data_hora else None,
        "sucesso": bool(msg.sucesso),
        "erro": msg.erro or "",
        "origem": msg.origem or "",
        "enviado_por": msg.enviado_por.username if getattr(msg, "enviado_por_id", None) else None,
        "venda_id": msg.venda_id,
    }


def _serializar_conversa_base(telefone: str, ultima=None, usuario=None) -> dict:
    venda = None
    if ultima is not None and ultima.venda_id:
        venda = ultima.venda
    if venda is None:
        venda = _venda_cabecalho(telefone, usuario)
    janela = estado_janela(telefone)
    preview = ""
    if ultima is not None:
        preview = (ultima.texto or "").replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:90] + "…"
    return {
        "telefone": canonicalizar_telefone(telefone),
        "telefone_exibicao": exibir_telefone(telefone),
        "cliente": _nome_cliente(venda),
        "venda_id": venda.id if venda is not None else None,
        "ultima_mensagem": preview,
        "ultima_direcao": ultima.direcao if ultima is not None else None,
        "ultima_tipo": ultima.tipo if ultima is not None else None,
        "ultima_em": ultima.data_hora.isoformat() if ultima is not None and ultima.data_hora else None,
        "janela_aberta": janela["aberta"],
        "janela_ate": janela["ate"].isoformat() if janela["ate"] else None,
        "aviso_janela": janela["aviso"],
        "bot_pausado": bot_pausado(telefone),
    }


def listar_conversas(usuario, busca: str = "", limite: int = 80) -> list[dict]:
    qs = _qs_visivel(usuario).select_related("venda__cliente", "venda__plano", "enviado_por")
    termo = (busca or "").strip()
    if termo:
        digitos = "".join(ch for ch in termo if ch.isdigit())
        filtro = Q(venda__cliente__nome_razao_social__icontains=termo) | Q(texto__icontains=termo)
        if digitos:
            filtro |= Q(telefone__icontains=digitos)
        qs = qs.filter(filtro)

    telefones = list(
        qs.values("telefone").annotate(ultima=Max("data_hora")).order_by("-ultima")[:limite]
    )
    itens = []
    for row in telefones:
        tel = row["telefone"]
        ultima = (
            qs.filter(telefone=tel).order_by("-data_hora", "-id").first()
        )
        if ultima is None:
            continue
        itens.append(_serializar_conversa_base(tel, ultima, usuario))
    return itens


def detalhe_conversa(usuario, telefone: str) -> Optional[dict]:
    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return None
    if not conversa_visivel(usuario, tel):
        return None
    chaves = telefones_equivalentes(tel)
    mensagens = list(
        _qs_visivel(usuario)
        .filter(telefone__in=chaves)
        .select_related("venda__cliente", "enviado_por")
        .order_by("data_hora", "id")
    )
    if not mensagens:
        return None
    ultima = mensagens[-1]
    base = _serializar_conversa_base(tel, ultima, usuario)
    canal_pronto = canal_oficial_pronto()
    base["canal_oficial_pronto"] = canal_pronto
    base["aviso_canal"] = "" if canal_pronto else AVISO_CANAL_INDISPONIVEL
    base["pode_texto_livre"] = base["janela_aberta"] and canal_pronto
    base["mensagens"] = [serializar_mensagem(m) for m in mensagens]
    return base


def assumir_conversa(usuario, telefone: str) -> Optional[dict]:
    tel = canonicalizar_telefone(telefone)
    if len(tel) < 10 or not conversa_visivel(usuario, tel):
        return None
    pausar_bot(tel, usuario, "Conversa assumida no atendimento WhatsApp")
    return detalhe_conversa(usuario, tel)


def responder_texto(usuario, telefone: str, texto: str) -> tuple[str, dict]:
    """
    Envia texto livre se a janela de 24h estiver aberta.
    Retorna (codigo, payload): ok | janela_fechada | canal_indisponivel | invalido |
    falha_envio | nao_encontrado.
    """
    from crm_app.models import MensagemWhatsAppAtendimento
    from crm_app.whatsapp_service import WhatsAppService

    tel = canonicalizar_telefone(telefone)
    corpo = (texto or "").strip()
    if len(tel) < 10 or not corpo:
        return "invalido", {"detail": "Informe o telefone e o texto da resposta."}
    if not conversa_visivel(usuario, tel):
        return "nao_encontrado", {"detail": "Conversa não encontrada."}

    janela = estado_janela(tel)
    if not janela["aberta"]:
        return "janela_fechada", {
            "detail": janela["aviso"],
            "janela_aberta": False,
            "codigo": "janela_fechada",
        }

    if not canal_oficial_pronto():
        return "canal_indisponivel", {
            "detail": "A resposta não foi enviada. " + AVISO_CANAL_INDISPONIVEL,
            "janela_aberta": True,
            "codigo": "canal_indisponivel",
        }

    pausar_bot(tel, usuario, "Resposta humana no atendimento WhatsApp")
    with contexto_registro_saida(
        origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
        enviado_por=usuario,
    ):
        ok, resp = WhatsAppService.para_cliente().enviar_mensagem_texto(
            tel, corpo, variar=False
        )
    if not ok:
        return "falha_envio", {
            "detail": "A Cloud API não confirmou o envio. A tentativa ficou registrada na conversa.",
            "janela_aberta": True,
            "codigo": "falha_envio",
            "conversa": detalhe_conversa(usuario, tel),
        }
    return "ok", {
        "ok": True,
        "janela_aberta": True,
        "bot_pausado": True,
        "conversa": detalhe_conversa(usuario, tel),
    }
