"""Envia mensagem de teste ao WhatsApp Nio (21 3605-1000) via WhatsAtende (Número A)."""
from __future__ import annotations

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from crm_app.services.whatsapp.whatsatende_provider import WhatsAtendeProvider  # noqa: E402


def main() -> int:
    destino = "552136051000"
    texto = "oi"
    provider = WhatsAtendeProvider(role="interno")
    if not provider.token:
        print("WHATSATENDE_TOKEN não configurado no .env", file=sys.stderr)
        return 2
    print(f"Enviando '{texto}' para {destino} via WhatsAtende (Número A)...")
    resp = provider.enviar_mensagem_texto(destino, texto)
    print("Resposta API:", resp)
    ok = provider.resposta_indica_sucesso(resp)
    print("Sucesso:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
