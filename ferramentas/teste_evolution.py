#!/usr/bin/env python3
"""Testes manuais do provider Evolution (envio e verificacao)."""
from __future__ import annotations

import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from crm_app.whatsapp_service import WhatsAppService  # noqa: E402


def main() -> int:
    provider = os.environ.get("WHATSAPP_PROVIDER", "zapi")
    print(f"WHATSAPP_PROVIDER={provider}")

    svc = WhatsAppService()
    telefone = os.environ.get("TESTE_WPP_TELEFONE", "5531988804000")
    print(f"Verificando numero {telefone}...")
    existe = svc.verificar_numero_existe(telefone)
    print(f"  exists={existe!r}")

    msg = os.environ.get("TESTE_WPP_MENSAGEM", "Teste Evolution site-record")
    if os.environ.get("TESTE_WPP_ENVIAR", "").lower() in ("1", "true", "sim"):
        ok, resp = svc.enviar_mensagem_texto(telefone, msg, variar=False)
        print(f"  envio ok={ok} resp={resp}")

    base = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
    inst = os.environ.get("EVOLUTION_INSTANCE_NAME", "site_record_zap")
    key = os.environ.get("EVOLUTION_API_KEY", "")
    if base and key:
        url = f"{base}/instance/connectionState/{inst}"
        r = requests.get(url, headers={"apikey": key}, timeout=20)
        print(f"Connection state HTTP {r.status_code}: {r.text[:200]}")

    grupos = svc.listar_grupos()
    print(f"Grupos: {len(grupos)} encontrados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
