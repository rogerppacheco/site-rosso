# crm_app/gemini_service.py
"""
Serviço para respostas com Gemini API (REST), no contexto do sistema/site.
Usado quando um vendedor envia mensagem que não é um comando do bot:
a IA interpreta e responde com base no conhecimento do sistema.
Usa requests para evitar conflito de dependências com protobuf.
"""
import os
import logging
import time
import requests

logger = logging.getLogger(__name__)

# Retry em 429 (Too Many Requests): esperar e tentar de novo
GEMINI_MAX_RETRIES_429 = 2
GEMINI_RETRY_DELAY_SEC = 2

# Chave da API: use variável de ambiente GEMINI_API_KEY (nunca commitar a chave).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# URL da API REST Gemini (generateContent)
# gemini-1.5-flash-latest retornava 404; usar gemini-2.0-flash (suportado na API)
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def _contexto_sistema(contexto_externo: bool = False) -> str:
    """Contexto do bot + base de conhecimento. contexto_externo=True para contatos não cadastrados."""
    from crm_app.ai_context import get_contexto_sistema
    return get_contexto_sistema(contexto_externo=contexto_externo)


def responder_com_gemini_custom(mensagem_usuario: str, system_prompt: str) -> str | None:
    """Gemini com systemInstruction customizado."""
    if not GEMINI_API_KEY:
        return None
    mensagem_usuario = (mensagem_usuario or "").strip()
    system_prompt = (system_prompt or "").strip()
    if not mensagem_usuario or not system_prompt:
        return None

    payload = {
        "contents": [{"parts": [{"text": mensagem_usuario}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"maxOutputTokens": 512, "temperature": 0.3},
    }
    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        if not parts:
            return None
        text = (parts[0].get("text") or "").strip()
        return text or None
    except Exception as e:
        logger.warning("[Gemini] Erro (custom): %s", e)
        return None


def responder_com_gemini(mensagem_usuario: str, nome_vendedor: str = "", contexto_externo: bool = False) -> str | None:
    """
    Envia a mensagem do usuário ao Gemini (REST) com o contexto do sistema e retorna a resposta em texto.
    Retorna None em caso de erro ou se GEMINI_API_KEY não estiver configurada.
    contexto_externo=True: usa prompt curto para contatos não cadastrados.
    """
    if not GEMINI_API_KEY:
        logger.warning("[Gemini] GEMINI_API_KEY não configurada. Configure a variável de ambiente para ativar respostas da IA.")
        return None

    mensagem_usuario = (mensagem_usuario or "").strip()
    if not mensagem_usuario:
        return None

    user_content = mensagem_usuario
    if nome_vendedor and not contexto_externo:
        user_content = f"[Mensagem do vendedor {nome_vendedor}]: {user_content}"

    payload = {
        "contents": [{"parts": [{"text": user_content}]}],
        "systemInstruction": {
            "parts": [{"text": _contexto_sistema(contexto_externo=contexto_externo).strip()}],
        },
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.4,
        },
    }

    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    for attempt in range(GEMINI_MAX_RETRIES_429 + 1):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 429:
                if attempt < GEMINI_MAX_RETRIES_429:
                    logger.warning(
                        "[Gemini] 429 Too Many Requests (cota/rate limit). Tentando novamente em %ss (tentativa %d/%d).",
                        GEMINI_RETRY_DELAY_SEC, attempt + 1, GEMINI_MAX_RETRIES_429 + 1,
                    )
                    time.sleep(GEMINI_RETRY_DELAY_SEC)
                    continue
                logger.warning(
                    "[Gemini] 429 Too Many Requests após %d tentativas. Cota da API excedida; verifique uso no Google AI Studio.",
                    GEMINI_MAX_RETRIES_429 + 1,
                )
                return None
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.RequestException as e:
            if getattr(e, "response", None) and getattr(e.response, "status_code", None) == 429:
                if attempt < GEMINI_MAX_RETRIES_429:
                    time.sleep(GEMINI_RETRY_DELAY_SEC)
                    continue
                logger.warning("[Gemini] 429 Too Many Requests (cota excedida). Configure limite no Google AI Studio ou aguarde.")
                return None
            logger.warning("[Gemini] Erro de rede/HTTP: %s", e)
            return None

    try:
        # Resposta: data["candidates"][0]["content"]["parts"][0]["text"]
        candidates = data.get("candidates") or []
        if not candidates:
            logger.warning("[Gemini] Resposta sem candidates.")
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        if not parts:
            logger.warning("[Gemini] Resposta sem parts.")
            return None
        text = (parts[0].get("text") or "").strip()
        if not text:
            return None
        return text
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("[Gemini] Erro ao interpretar resposta: %s", e)
        return None
    except Exception as e:
        logger.exception("[Gemini] Erro ao chamar API: %s", e)
        return None
