#!/usr/bin/env python3
"""
Provisiona instância Evolution `site_record_zap` e configura webhook do site-record.

Uso (variáveis de ambiente):
  EVOLUTION_API_URL=https://evolution-api-production-8bbb.up.railway.app
  EVOLUTION_API_KEY=sua-apikey
  EVOLUTION_INSTANCE_NAME=site_record_zap
  SITE_RECORD_WEBHOOK_URL=https://www.recordpap.com.br/api/crm/webhook-whatsapp/

  python ferramentas/setup_evolution_site_record.py
  python ferramentas/setup_evolution_site_record.py --qrcode
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import requests

DEFAULT_INSTANCE = "site_record_zap"
DEFAULT_WEBHOOK = "https://www.recordpap.com.br/api/crm/webhook-whatsapp/"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _headers(api_key: str) -> Dict[str, str]:
    return {"apikey": api_key, "Content-Type": "application/json"}


def _request(
    method: str,
    base_url: str,
    path: str,
    api_key: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    resp = requests.request(
        method,
        url,
        headers=_headers(api_key),
        json=payload,
        timeout=timeout,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {resp.status_code} {method} {path}: {data}")
    return data if isinstance(data, dict) else {"data": data}


def criar_instancia(base_url: str, api_key: str, instance_name: str) -> None:
    payload = {
        "instanceName": instance_name,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
    }
    try:
        data = _request("POST", base_url, "/instance/create", api_key, payload)
        print(f"Instância criada ou já existente: {json.dumps(data, ensure_ascii=False)[:500]}")
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "already" in msg or "exists" in msg or "409" in msg:
            print(f"Instância {instance_name} já existe — continuando.")
        else:
            raise


def configurar_webhook(base_url: str, api_key: str, instance_name: str, webhook_url: str) -> None:
    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": [
                "MESSAGES_UPSERT",
                "SEND_MESSAGE",
                "CONNECTION_UPDATE",
            ],
        }
    }
    path = f"/webhook/set/{instance_name}"
    data = _request("POST", base_url, path, api_key, payload)
    print(f"Webhook configurado: {webhook_url}")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:800])


def status_conexao(base_url: str, api_key: str, instance_name: str) -> Dict[str, Any]:
    path = f"/instance/connectionState/{instance_name}"
    return _request("GET", base_url, path, api_key)


def obter_qrcode(base_url: str, api_key: str, instance_name: str) -> Optional[str]:
    path = f"/instance/connect/{instance_name}"
    data = _request("GET", base_url, path, api_key)
    for key in ("base64", "code"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    qrcode = data.get("qrcode")
    if isinstance(qrcode, dict) and qrcode.get("base64"):
        return qrcode["base64"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup Evolution site_record_zap")
    parser.add_argument("--qrcode", action="store_true", help="Exibe QR após criar instância")
    parser.add_argument("--skip-create", action="store_true", help="Não chama instance/create")
    args = parser.parse_args()

    base_url = _env("EVOLUTION_API_URL")
    api_key = _env("EVOLUTION_API_KEY")
    instance_name = _env("EVOLUTION_INSTANCE_NAME", DEFAULT_INSTANCE)
    webhook_url = _env("SITE_RECORD_WEBHOOK_URL", DEFAULT_WEBHOOK)

    if not base_url or not api_key:
        print("Defina EVOLUTION_API_URL e EVOLUTION_API_KEY.", file=sys.stderr)
        return 1

    print(f"Evolution: {base_url}")
    print(f"Instância: {instance_name}")
    print(f"Webhook:   {webhook_url}")

    if not args.skip_create:
        criar_instancia(base_url, api_key, instance_name)

    configurar_webhook(base_url, api_key, instance_name, webhook_url)

    st = status_conexao(base_url, api_key, instance_name)
    print(f"Status conexão: {json.dumps(st, ensure_ascii=False)}")

    if args.qrcode:
        for attempt in range(1, 6):
            qr = obter_qrcode(base_url, api_key, instance_name)
            if qr:
                print("\nQR Code (base64 — cole em data URI no navegador ou painel Admin):")
                if not qr.startswith("data:"):
                    qr = f"data:image/png;base64,{qr}"
                print(qr[:120] + "... [truncado]")
                break
            print(f"QR ainda indisponível (tentativa {attempt}/5)...")
            time.sleep(2)

    print("\nPróximos passos Railway (site-record — Opção B híbrida):")
    print("  WHATSAPP_PROVIDER=evolution")
    print(f"  EVOLUTION_API_URL={base_url}")
    print("  EVOLUTION_API_KEY=<mesma apikey>")
    print(f"  EVOLUTION_INSTANCE_NAME={instance_name}")
    print("  N8N_OUTBOUND_WEBHOOK_URL=<webhook n8n site-record-enviar-mensagem>")
    print("\n  python ferramentas/n8n/deploy_site_record_outbound_flow.py --dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
