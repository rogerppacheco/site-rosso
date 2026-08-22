# crm_app/groq_service.py
"""
Respostas com Groq API (REST, OpenAI-compatible).
Cota gratuita generosa (~14.400 req/dia). Usado como primeira opção antes do Gemini.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _contexto_sistema(reduzido: bool = False, contexto_externo: bool = False) -> str:
    """Contexto do bot + base de conhecimento. reduzido=True omite documentos/URLs (para retry após 413). contexto_externo=True para contatos não cadastrados."""
    from crm_app.ai_context import get_contexto_sistema
    return get_contexto_sistema(reduzido=reduzido, contexto_externo=contexto_externo)


def responder_com_groq_custom(mensagem_usuario: str, system_prompt: str) -> str | None:
    """Groq com prompt de sistema customizado (ex.: atendimento ao cliente com dados do pedido)."""
    if not GROQ_API_KEY:
        return None
    mensagem_usuario = (mensagem_usuario or "").strip()
    system_prompt = (system_prompt or "").strip()
    if not mensagem_usuario or not system_prompt:
        return None
    try:
        resp = requests.post(
            GROQ_API_URL,
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": mensagem_usuario},
                ],
                "max_tokens": 512,
                "temperature": 0.3,
            },
            timeout=30,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        choices = resp.json().get("choices") or []
        if not choices:
            return None
        text = (choices[0].get("message") or {}).get("content") or ""
        return text.strip() or None
    except Exception as e:
        logger.warning("[Groq] Erro (custom): %s", e)
        return None


def responder_com_groq(mensagem_usuario: str, nome_vendedor: str = "", contexto_externo: bool = False) -> str | None:
    """
    Envia a mensagem ao Groq (Llama) e retorna a resposta em texto.
    Retorna None se GROQ_API_KEY não estiver configurada ou em caso de erro.
    contexto_externo=True: usa prompt curto para contatos não cadastrados.
    """
    if not GROQ_API_KEY:
        logger.debug("[Groq] GROQ_API_KEY não configurada.")
        return None

    mensagem_usuario = (mensagem_usuario or "").strip()
    if not mensagem_usuario:
        return None

    user_content = mensagem_usuario
    if nome_vendedor and not contexto_externo:
        user_content = f"[Mensagem do vendedor {nome_vendedor}]: {user_content}"

    def _enviar(reduzido: bool = False):
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": _contexto_sistema(reduzido=reduzido, contexto_externo=contexto_externo).strip()},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 1024,
            "temperature": 0.4,
        }
        return requests.post(
            GROQ_API_URL,
            json=payload,
            timeout=30,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
        )

    try:
        resp = _enviar(reduzido=False)
        if resp.status_code == 413:
            logger.warning(
                "[Groq] 413 Payload Too Large. Tentando com contexto reduzido (sem documentos/URLs). "
                "A IA ficará sem os planos Nio que estão nos documentos. Reduza IA_MAX_CHARS_DOCS/URLS no .env."
            )
            resp = _enviar(reduzido=True)
        else:
            logger.debug("[Groq] Contexto completo enviado (documentos e URLs incluídos).")
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            logger.warning("[Groq] Resposta sem choices.")
            return None
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            return None
        return text
    except requests.exceptions.RequestException as e:
        logger.warning("[Groq] Erro de rede/HTTP: %s", e)
        return None
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("[Groq] Erro ao interpretar resposta: %s", e)
        return None
    except Exception as e:
        logger.exception("[Groq] Erro ao chamar API: %s", e)
        return None
