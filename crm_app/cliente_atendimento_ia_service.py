# crm_app/cliente_atendimento_ia_service.py
"""
Atendimento automático a clientes cujo telefone está cadastrado em uma Venda.
Responde com dados reais do pedido (agendamento, instalação, status, O.S.)
e notifica BackOffice e Diretoria no WhatsApp.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

_AVISO_CACHE_TTL = 7200  # 2h — evita spam de avisos ao BO/Diretoria
_AVISO_CACHE_PREFIX = "cliente_contato_aviso"


def _digits_only(s: str) -> str:
    if not s:
        return ""
    return "".join(filter(str.isdigit, str(s)))


def formatar_telefone(telefone: str) -> str:
    if not telefone:
        return ""
    telefone_limpo = _digits_only(telefone)
    if telefone_limpo.startswith("55") and len(telefone_limpo) > 12:
        telefone_limpo = telefone_limpo[2:]
    return telefone_limpo


def chaves_telefone_variantes(telefone: str) -> list[str]:
    base = formatar_telefone(telefone) or ""
    if not base:
        return []
    chaves = [base]
    if base.startswith("55") and len(base) > 11:
        chaves.append(base[2:])
    elif len(base) >= 10 and not base.startswith("55"):
        chaves.append("55" + base)
    nacional = base[2:] if base.startswith("55") and len(base) > 11 else base
    if len(nacional) == 10:
        chaves.append(nacional[:2] + "9" + nacional[2:])
        chaves.append("55" + nacional[:2] + "9" + nacional[2:])
    if len(nacional) == 11 and nacional[2] == "9":
        chaves.append(nacional[:2] + nacional[3:])
        chaves.append("55" + nacional[:2] + nacional[3:])
    if len(base) == 12 and base.startswith("55") and len(base) >= 5 and base[4] != "9":
        chaves.append(base[:4] + "9" + base[4:])
    if len(base) == 13 and base.startswith("55") and len(base) >= 6 and base[4] == "9":
        chaves.append(base[:4] + base[5:])
    return list(dict.fromkeys(chaves))


def _telefone_casa_com_chave(cadastro: str, chaves_digits: list[str]) -> bool:
    if not cadastro:
        return False
    dig = _digits_only(cadastro)
    if not dig or len(dig) < 8:
        return False
    for k in chaves_digits:
        if not k or len(k) < 8:
            continue
        if dig == k or dig.endswith(k) or k.endswith(dig):
            return True
        if len(k) >= 10 and len(dig) >= 10:
            if dig[-10:] == k[-10:] or dig[-11:] == k[-11:]:
                return True
    return False


def buscar_venda_ativa_por_telefone_cliente(telefone: str):
    """
    Retorna a Venda ativa mais recente cujo telefone1 ou telefone2 coincide com o número.
    """
    from crm_app.models import Venda

    chaves = chaves_telefone_variantes(telefone)
    if not chaves:
        return None
    chaves_digits = [_digits_only(c) for c in chaves if _digits_only(c)]

    q = Q()
    for c in chaves:
        if len(c) >= 8:
            q |= Q(telefone1__icontains=c) | Q(telefone2__icontains=c)
    if not q:
        return None

    candidatas = list(
        Venda.objects.filter(ativo=True)
        .filter(q)
        .select_related("cliente", "vendedor", "status_esteira", "status_tratamento", "plano")
        .order_by("-data_criacao")[:10]
    )
    if not candidatas:
        return None

    for v in candidatas:
        if _telefone_casa_com_chave(v.telefone1, chaves_digits) or _telefone_casa_com_chave(
            v.telefone2, chaves_digits
        ):
            return v

    return candidatas[0]


def _fmt_data(d) -> str:
    if not d:
        return "não informada"
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:
        return str(d)


def _periodo_label(periodo: str) -> str:
    if periodo == "MANHA":
        return "Manhã (8h às 12h)"
    if periodo == "TARDE":
        return "Tarde (13h às 18h)"
    return periodo or "não informado"


def _snapshot_pedido(venda) -> dict:
    cliente_nome = ""
    if venda.cliente_id:
        cliente_nome = (venda.cliente.nome_razao_social or "").strip()
    vendedor_nome = ""
    if venda.vendedor_id:
        vendedor_nome = (
            venda.vendedor.get_full_name() or venda.vendedor.username or ""
        ).strip()
    plano_nome = ""
    if venda.plano_id:
        plano_nome = (getattr(venda.plano, "nome", None) or str(venda.plano)).strip()
    return {
        "venda_id": venda.id,
        "cliente_nome": cliente_nome or "Cliente",
        "ordem_servico": (venda.ordem_servico or "").strip() or "ainda não gerada",
        "data_agendamento": _fmt_data(venda.data_agendamento),
        "periodo_agendamento": _periodo_label(venda.periodo_agendamento or ""),
        "data_instalacao": _fmt_data(venda.data_instalacao),
        "data_instalacao_fisica": _fmt_data(venda.data_instalacao_fisica),
        "status_esteira": (
            venda.status_esteira.nome if venda.status_esteira_id else "não informado"
        ),
        "status_tratamento": (
            venda.status_tratamento.nome if venda.status_tratamento_id else "não informado"
        ),
        "plano": plano_nome or "não informado",
        "vendedor": vendedor_nome or "não informado",
        "cidade": (venda.cidade or "").strip(),
        "estado": (venda.estado or "").strip(),
    }


def _classificar_intencao(mensagem: str) -> str:
    t = (mensagem or "").lower().strip()
    if not t:
        return "OUTROS"
    if any(
        x in t
        for x in (
            "atendente",
            "humano",
            "pessoa",
            "falar com",
            "especialista",
            "reclama",
            "reclamação",
            "reclamacao",
            "cancelar",
            "desistir",
            "procon",
            "ouvidoria",
        )
    ):
        return "HUMANO"
    if any(
        x in t
        for x in (
            "agendad",
            "agendamento",
            "que dia",
            "qual dia",
            "quando vão",
            "quando vao",
            "data da instala",
            "horário",
            "horario",
            "manhã",
            "manha",
            "tarde",
            "período",
            "periodo",
        )
    ):
        return "AGENDAMENTO"
    if any(
        x in t
        for x in (
            "instal",
            "já instal",
            "ja instal",
            "foi instal",
            "técnico",
            "tecnico",
        )
    ):
        return "INSTALACAO"
    if any(x in t for x in ("ordem de serviço", "ordem de servico", " o.s", " os ", "número da os", "numero da os")):
        return "OS"
    if any(
        x in t
        for x in (
            "status",
            "andamento",
            "situação",
            "situacao",
            "meu pedido",
            "como está",
            "como esta",
            "andamento do pedido",
        )
    ):
        return "STATUS"
    if "?" in t or t.startswith(("qual", "quando", "como", "onde", "tem ")):
        return "OUTROS"
    return "OUTROS"


def _resposta_template(intent: str, snap: dict) -> str | None:
    nome = snap["cliente_nome"].split()[0] if snap["cliente_nome"] else "Cliente"

    if intent == "AGENDAMENTO":
        if snap["data_agendamento"] == "não informada":
            return (
                f"Olá, {nome}. Verifiquei seu pedido: ainda não há data de agendamento registrada.\n"
                f"Status na esteira: *{snap['status_esteira']}*.\n"
                "Nossa equipe retornará com a data em breve. Permaneço à disposição."
            )
        return (
            f"Olá, {nome}. Seu agendamento está previsto para *{snap['data_agendamento']}*, "
            f"período da *{snap['periodo_agendamento']}*.\n"
            "O técnico entrará em contato por ligação e WhatsApp quando estiver a caminho."
        )

    if intent == "INSTALACAO":
        if snap["data_instalacao_fisica"] != "não informada":
            return (
                f"Olá, {nome}. Consta instalação realizada em *{snap['data_instalacao_fisica']}*.\n"
                "Se precisar de suporte técnico, digite *SUPORTE* ou aguarde nosso retorno."
            )
        if snap["data_instalacao"] != "não informada":
            return (
                f"Olá, {nome}. A instalação está registrada para *{snap['data_instalacao']}*.\n"
                f"Agendamento: *{snap['data_agendamento']}* ({snap['periodo_agendamento']})."
            )
        return (
            f"Olá, {nome}. A instalação ainda não foi concluída.\n"
            f"Agendamento: *{snap['data_agendamento']}* — *{snap['periodo_agendamento']}*.\n"
            f"Status: *{snap['status_esteira']}*."
        )

    if intent == "STATUS":
        return (
            f"Olá, {nome}. Segue o andamento do seu pedido:\n"
            f"• Esteira: *{snap['status_esteira']}*\n"
            f"• Tratamento: *{snap['status_tratamento']}*\n"
            f"• Agendamento: *{snap['data_agendamento']}* ({snap['periodo_agendamento']})\n"
            f"• O.S.: *{snap['ordem_servico']}*"
        )

    if intent == "OS":
        return (
            f"Olá, {nome}. O número da sua ordem de serviço é: *{snap['ordem_servico']}*.\n"
            f"Status na esteira: *{snap['status_esteira']}*."
        )

    if intent == "HUMANO":
        return (
            f"Olá, {nome}. Recebi sua mensagem.\n"
            "Em breve um de nossos especialistas entrará em contato com você. "
            "Agradecemos a compreensão."
        )

    return None


def _contexto_pedido_texto(snap: dict) -> str:
    local = ""
    if snap.get("cidade") or snap.get("estado"):
        local = f"{snap.get('cidade', '')}/{snap.get('estado', '')}".strip("/")
    return f"""
Dados do pedido do cliente (use APENAS estas informações; não invente):
- Cliente: {snap['cliente_nome']}
- Plano: {snap['plano']}
- O.S.: {snap['ordem_servico']}
- Agendamento: {snap['data_agendamento']} — {snap['periodo_agendamento']}
- Instalação (sistema): {snap['data_instalacao']}
- Instalação física (concluída): {snap['data_instalacao_fisica']}
- Status esteira: {snap['status_esteira']}
- Status tratamento: {snap['status_tratamento']}
- Consultor: {snap['vendedor']}
{f'- Local: {local}' if local else ''}
""".strip()


def _usuarios_backoffice_diretoria():
    from usuarios.models import Usuario

    return (
        Usuario.objects.filter(is_active=True, groups__name__in=["BackOffice", "Diretoria"])
        .distinct()
        .only("id", "username", "tel_whatsapp", "tel_whatsapp_2", "tel_whatsapp_3")
    )


def _telefones_whatsapp_usuario(usuario) -> list[str]:
    out = []
    for attr in ("tel_whatsapp", "tel_whatsapp_2", "tel_whatsapp_3"):
        raw = (getattr(usuario, attr, None) or "").strip()
        if not raw:
            continue
        dig = _digits_only(raw)
        if len(dig) >= 10:
            out.append(dig)
    return list(dict.fromkeys(out))


def _enviar_aviso_backoffice_diretoria(
    venda,
    telefone_cliente: str,
    mensagem_cliente: str,
    snap: dict,
) -> int:
    chave_cache = f"{_AVISO_CACHE_PREFIX}:{venda.id}:{formatar_telefone(telefone_cliente)}"
    if cache.get(chave_cache):
        logger.debug("[ClienteAtendimento] Aviso BO/Diretoria em cache (já enviado recentemente).")
        return 0

    destinatarios = _usuarios_backoffice_diretoria()
    if not destinatarios.exists():
        logger.warning("[ClienteAtendimento] Nenhum usuário BackOffice/Diretoria ativo para aviso.")
        return 0

    preview = (mensagem_cliente or "").strip().replace("\n", " ")
    if len(preview) > 200:
        preview = preview[:197] + "..."
    tel_fmt = formatar_telefone(telefone_cliente) or telefone_cliente
    texto = (
        "📱 *Cliente entrou em contato* (número cadastrado em venda)\n\n"
        f"👤 *Cliente:* {snap['cliente_nome']}\n"
        f"📞 *Telefone:* {tel_fmt}\n"
        f"📋 *O.S.:* {snap['ordem_servico']}\n"
        f"📊 *Esteira:* {snap['status_esteira']}\n"
        f"📅 *Agendamento:* {snap['data_agendamento']} ({snap['periodo_agendamento']})\n"
        f"👔 *Consultor:* {snap['vendedor']}\n"
        f"🆔 *Venda:* #{venda.id}\n\n"
        f"💬 *Mensagem:* \"{preview or '(sem texto)'}\""
    )

    try:
        from crm_app.whatsapp_service import WhatsAppService

        svc = WhatsAppService()
    except Exception as e:
        logger.warning("[ClienteAtendimento] WhatsAppService indisponível: %s", e)
        return 0

    enviados = 0
    vistos = set()
    for u in destinatarios:
        for tel in _telefones_whatsapp_usuario(u):
            if tel in vistos:
                continue
            vistos.add(tel)
            try:
                ok, _ = svc.enviar_mensagem_texto(tel, texto)
                if ok:
                    enviados += 1
            except Exception as e:
                logger.debug("[ClienteAtendimento] Falha aviso para %s (%s): %s", u.username, tel, e)

    if enviados:
        cache.set(chave_cache, True, _AVISO_CACHE_TTL)
        logger.info(
            "[ClienteAtendimento] Aviso enviado a %s destino(s) BO/Diretoria (venda #%s).",
            enviados,
            venda.id,
        )
    return enviados


def _registrar_historico_atendimento(
    venda,
    telefone_cliente: str,
    mensagem_cliente: str,
    resposta_sistema: str,
    intencao: str,
    fonte_resposta: str,
    origem: str,
    avisos_bo_enviados: int,
) -> None:
    try:
        from crm_app.models import HistoricoAtendimentoIACliente

        HistoricoAtendimentoIACliente.objects.create(
            venda=venda,
            telefone=formatar_telefone(telefone_cliente) or telefone_cliente,
            mensagem_cliente=(mensagem_cliente or "")[:10000],
            resposta_sistema=(resposta_sistema or "")[:10000],
            intencao=intencao if intencao in dict(HistoricoAtendimentoIACliente.INTENCAO_CHOICES) else "OUTROS",
            fonte_resposta=fonte_resposta
            if fonte_resposta in dict(HistoricoAtendimentoIACliente.FONTE_RESPOSTA_CHOICES)
            else "TEMPLATE",
            origem=origem if origem in dict(HistoricoAtendimentoIACliente.ORIGEM_CHOICES) else "WEBHOOK",
            avisos_bo_enviados=max(0, int(avisos_bo_enviados or 0)),
        )
    except Exception as e:
        logger.warning("[ClienteAtendimento] Falha ao registrar histórico no banco: %s", e)


def processar_mensagem_cliente_venda(
    telefone_cliente: str,
    mensagem: str,
    *,
    origem: str = "WEBHOOK",
) -> str | None:
    """
    Se o telefone pertence a uma venda ativa, gera resposta factual e avisa BO/Diretoria.
    Registra cada interação em HistoricoAtendimentoIACliente.
    Retorna texto para enviar ao cliente ou None se não houver venda correspondente.
    """
    venda = buscar_venda_ativa_por_telefone_cliente(telefone_cliente)
    if not venda:
        return None

    snap = _snapshot_pedido(venda)
    texto_msg = (mensagem or "").strip()
    avisos_bo = 0

    try:
        avisos_bo = _enviar_aviso_backoffice_diretoria(venda, telefone_cliente, texto_msg, snap)
    except Exception as e:
        logger.warning("[ClienteAtendimento] Erro ao enviar aviso BO/Diretoria: %s", e)

    intent = _classificar_intencao(texto_msg)
    resposta = _resposta_template(intent, snap)
    fonte_resposta = "TEMPLATE" if resposta else ""

    if not resposta and intent == "OUTROS" and texto_msg:
        try:
            from crm_app.ai_chat_service import responder_cliente_com_contexto_pedido

            resposta = responder_cliente_com_contexto_pedido(
                texto_msg,
                _contexto_pedido_texto(snap),
                nome_cliente=snap["cliente_nome"],
            )
            if resposta:
                fonte_resposta = "IA"
        except Exception as e:
            logger.warning("[ClienteAtendimento] IA com contexto do pedido falhou: %s", e)

    if not resposta:
        fonte_resposta = "FALLBACK"
        resposta = (
            f"Olá, {snap['cliente_nome'].split()[0] if snap['cliente_nome'] else 'Cliente'}. "
            "Recebi sua mensagem sobre seu pedido Nio Fibra.\n\n"
            f"• Agendamento: *{snap['data_agendamento']}* ({snap['periodo_agendamento']})\n"
            f"• Status: *{snap['status_esteira']}*\n"
            f"• O.S.: *{snap['ordem_servico']}*\n\n"
            "Para falar com um especialista, descreva sua dúvida ou aguarde nosso retorno."
        )

    resposta = resposta.strip()
    if not fonte_resposta:
        fonte_resposta = "TEMPLATE"

    _registrar_historico_atendimento(
        venda=venda,
        telefone_cliente=telefone_cliente,
        mensagem_cliente=texto_msg,
        resposta_sistema=resposta,
        intencao=intent,
        fonte_resposta=fonte_resposta,
        origem=origem,
        avisos_bo_enviados=avisos_bo,
    )

    return resposta
