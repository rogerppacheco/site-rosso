# crm_app/ai_chat_service.py
"""
Orquestrador de IA para dúvidas no WhatsApp: tenta Groq primeiro (cota gratuita maior),
depois Gemini como fallback.
"""
import logging

logger = logging.getLogger(__name__)


def responder_com_ia(mensagem_usuario: str, nome_vendedor: str = "", contexto_externo: bool = False) -> str | None:
    """
    Tenta responder usando IA: primeiro Groq, depois Gemini.
    Retorna o texto da resposta ou None se nenhum conseguir.
    contexto_externo=True: prompt para contatos não cadastrados (resposta acolhedora, analista retornará).
    """
    # 1) Groq (cota gratuita ~14.400 req/dia)
    try:
        from crm_app.groq_service import responder_com_groq
        resposta = responder_com_groq(mensagem_usuario, nome_vendedor=nome_vendedor, contexto_externo=contexto_externo)
        if resposta:
            logger.info("[IA] Resposta enviada via Groq.")
            return resposta
    except Exception as e:
        logger.warning("[IA] Groq falhou: %s", e)

    # 2) Gemini (fallback; cota free mais restrita)
    try:
        from crm_app.gemini_service import responder_com_gemini
        resposta = responder_com_gemini(mensagem_usuario, nome_vendedor=nome_vendedor, contexto_externo=contexto_externo)
        if resposta:
            logger.info("[IA] Resposta enviada via Gemini.")
            return resposta
    except Exception as e:
        logger.warning("[IA] Gemini falhou: %s", e)

    return None


def responder_cliente_com_contexto_pedido(
    mensagem_usuario: str,
    contexto_pedido: str,
    nome_cliente: str = "",
) -> str | None:
    """
    Responde ao cliente usando IA com fatos do pedido injetados (sem inventar dados).
    """
    mensagem_usuario = (mensagem_usuario or "").strip()
    contexto_pedido = (contexto_pedido or "").strip()
    if not mensagem_usuario or not contexto_pedido:
        return None

    primeiro_nome = (nome_cliente or "Cliente").split()[0]
    system = f"""
Você atende um cliente da Nio Fibra pelo WhatsApp (Record PAP).
Responda em português, tom cordial e profissional (sem abreviações: use "você", não "vc").
Use APENAS os dados do pedido abaixo. Se a informação não estiver nos dados, diga que um especialista retornará.
Não invente datas, status nem valores. Respostas curtas (ideal para WhatsApp).
Chame o cliente pelo primeiro nome quando possível: {primeiro_nome}.

{contexto_pedido}
""".strip()

    try:
        from crm_app.groq_service import responder_com_groq_custom
        resposta = responder_com_groq_custom(mensagem_usuario, system)
        if resposta:
            return resposta
    except Exception as e:
        logger.warning("[IA] Groq (cliente pedido) falhou: %s", e)

    try:
        from crm_app.gemini_service import responder_com_gemini_custom
        resposta = responder_com_gemini_custom(mensagem_usuario, system)
        if resposta:
            return resposta
    except Exception as e:
        logger.warning("[IA] Gemini (cliente pedido) falhou: %s", e)

    return None


def sugerir_status_boas_vindas(texto: str) -> str:
    """
    Sugere status para resposta do cliente às boas-vindas.
    Retorna: OK, ERRO_VENDAS, ERRO_TECNICO ou OUTROS.
    Usa regras por palavras-chave (pode ser ampliado com IA depois).
    """
    if not texto or not texto.strip():
        return 'OUTROS'
    t = texto.lower().strip()
    # Erro técnico: internet, velocidade, caiu, instável, não funciona, lento, etc.
    termos_tecnico = [
        'internet', 'velocidade', 'lento', 'lenta', 'caiu', 'cai', 'instável', 'instavel',
        'não funciona', 'nao funciona', 'não entrega', 'nao entrega', 'queda', 'sinal',
        'conexão', 'conexao', 'wi-fi', 'wifi', 'roteador', 'modem', 'fibra', 'reclamação',
        'reclamacao', 'problema técnico', 'problema tecnico', 'velocidade não', 'velocidade nao',
    ]
    for termo in termos_tecnico:
        if termo in t:
            return 'ERRO_TECNICO'
    # Erro de vendas: vendedor, prometeu, mentiu, atendimento, insatisfeito
    termos_vendas = [
        'vendedor', 'vendedora', 'prometeu', 'prometeu e não', 'mentiu', 'enganou',
        'atendimento ruim', 'atendimento péssimo', 'atendimento pessimo', 'insatisfeito',
        'insatisfeita', 'não era o que', 'nao era o que', 'diferente do que', 'esperava',
    ]
    for termo in termos_vendas:
        if termo in t:
            return 'ERRO_VENDAS'
    # OK: agradecimento, confirmação positiva
    termos_ok = ['obrigado', 'obrigada', 'valeu', 'ok', 'tudo bem', 'tudo certo', 'perfeito', 'ótimo', 'otimo']
    for termo in termos_ok:
        if termo in t and len(t) < 100:  # mensagem curta e positiva
            return 'OK'
    return 'OUTROS'
