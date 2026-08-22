"""
Gera WHATSATENDE_WEBHOOK_TOKEN (segredo do path do webhook).

Uso:
  python ferramentas/gerar_whatsatende_webhook_token.py
  python ferramentas/gerar_whatsatende_webhook_token.py --bytes 32
  python ferramentas/gerar_whatsatende_webhook_token.py --site-url https://www.recordpap.com.br
"""
from __future__ import annotations

import argparse
import secrets
import sys


def gerar_token(nbytes: int = 32) -> str:
    """Token URL-safe (sem caracteres problemáticos no path)."""
    if nbytes < 16:
        raise ValueError("Use pelo menos 16 bytes para o segredo.")
    return secrets.token_urlsafe(nbytes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera segredo para WHATSATENDE_WEBHOOK_TOKEN"
    )
    parser.add_argument(
        "--bytes",
        type=int,
        default=32,
        help="Entropia em bytes (padrão: 32 → ~43 caracteres URL-safe)",
    )
    parser.add_argument(
        "--site-url",
        default="https://www.recordpap.com.br",
        help="Base para montar a URL do webhook",
    )
    args = parser.parse_args(argv)

    try:
        token = gerar_token(args.bytes)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    site = (args.site_url or "").rstrip("/")
    url = f"{site}/api/crm/webhook-whatsapp/{token}/"

    print("=== WhatsAtende webhook token ===")
    print()
    print("Railway / .env:")
    print(f"WHATSATENDE_WEBHOOK_TOKEN={token}")
    print()
    print("URL para cadastrar na WhatsAtende:")
    print(url)
    print()
    print("Guarde o valor com segurança. Não versionar no Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
