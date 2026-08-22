"""
Utilitários para o fluxo de análise de crédito via WhatsApp.
Geração de celulares e emails para preencher campos no PAP.

O portal Nio valida o e-mail (envia teste e verifica entrega). Por isso precisamos de
endereços que existam de fato e aceitem receber e-mail. Plus addressing foi rejeitado
pelo Nio ("E-mail inválido"). Opções válidas:
- CREDITO_EMAILS: lista de e-mails reais (vírgula) — rotação aleatória entre eles.
- CREDITO_EMAIL_MAILINATOR=1: gera endereços @mailinator.com (aceitam envio; Nio pode bloquear domínio).
- Caso contrário: usa um único e-mail fixo (CREDITO_EMAIL_BASE).
"""
import os
import random
import string
import time

# DDD fixo 31 (região de BH/Contagem)
DDD_CREDITO = "31"

# E-mail fixo quando não há pool configurado (fallback)
CREDITO_EMAIL_BASE = "comunicacao@recordpap.com.br"

# Domínios de email conhecidos para gerar endereços (uso alternativo)
DOMINIOS_EMAIL = [
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com.br",
    "icloud.com",
]


def _get_credito_emails_pool():
    """Lista de e-mails válidos para rotação (CREDITO_EMAILS no settings ou env)."""
    try:
        from django.conf import settings
        s = getattr(settings, "CREDITO_EMAILS", None) or ""
    except Exception:
        s = os.environ.get("CREDITO_EMAILS", "")
    if not s or not isinstance(s, str):
        return []
    return [e.strip().lower() for e in s.split(",") if e.strip()]


def _use_mailinator():
    """Se deve usar endereços @mailinator.com (aceitam envio; Nio pode rejeitar o domínio)."""
    try:
        from django.conf import settings
        return getattr(settings, "CREDITO_EMAIL_MAILINATOR", False)
    except Exception:
        return os.environ.get("CREDITO_EMAIL_MAILINATOR", "").strip().lower() in ("1", "true", "yes")


def gerar_email_credito() -> str:
    """
    Retorna um e-mail para a análise de crédito no PAP/Nio.

    O Nio valida o e-mail (envia teste e verifica). Ordem de uso:
    1. Se CREDITO_EMAIL_MAILINATOR estiver ativo: gera xxx@mailinator.com (aceita envio; Nio pode bloquear).
    2. Se CREDITO_EMAILS estiver configurado: escolhe um aleatório do pool (e-mails reais que aceitam envio).
    3. Senão: retorna o e-mail fixo CREDITO_EMAIL_BASE (pode travar após muitas consultas).
    """
    if _use_mailinator():
        local = f"credito{int(time.time() * 1000)}{random.randint(100, 999)}"
        return f"{local}@mailinator.com"
    pool = _get_credito_emails_pool()
    if pool:
        return random.choice(pool)
    return CREDITO_EMAIL_BASE


def gerar_celular_random() -> str:
    """
    Gera um número de celular aleatório com DDD 31.
    Formato: 31 + 9 + 8 dígitos = 11 dígitos (ex: 31912345678)
    """
    # Celular brasileiro: 9XXXXXXXX (9 dígitos após DDD)
    sufixo = "".join(random.choices(string.digits, k=8))
    return f"{DDD_CREDITO}9{sufixo}"


def gerar_email_random() -> str:
    """
    Gera um email aleatório com domínio conhecido (gmail, hotmail, etc.).
    Formato: prefixo_único@dominio.com
    Evita colisões usando timestamp + random para o prefixo.
    Nota: esses endereços não existem de fato; se o site enviar email de teste,
    pode dar bounce. Para análise de crédito, prefira gerar_email_credito().
    """
    prefixo = f"credito{int(time.time() * 1000)}{random.randint(100, 999)}"
    dominio = random.choice(DOMINIOS_EMAIL)
    return f"{prefixo}@{dominio}"
