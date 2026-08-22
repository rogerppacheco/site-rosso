#!/usr/bin/env python3
"""
Publica ou atualiza o fluxo outbound Teams site-record no n8n (upsert + activate).

Variáveis de ambiente:
  N8N_API_URL=https://n8n-production-574f.up.railway.app
  N8N_API_KEY=<api key do n8n>
  TEAMS_INCOMING_WEBHOOK_URL=<Incoming Webhook do canal Teams no n8n>

Uso:
  python ferramentas/n8n/deploy_site_record_teams_outbound_flow.py
  python ferramentas/n8n/deploy_site_record_teams_outbound_flow.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

FLOW_FILE = Path(__file__).resolve().parent / "site-record-n8n-teams-outbound-flow.json"
FLOW_NAME = "Site Record — CRM → Teams (Outbound)"
WEBHOOK_PATH = "site-record-teams-notificar"
DEFAULT_N8N_BASE = "https://n8n-production-574f.up.railway.app"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _api_base(n8n_url: str) -> str:
    base = n8n_url.rstrip("/")
    if base.endswith("/api/v1"):
        return base
    return f"{base}/api/v1"


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "accept": "application/json",
        "X-N8N-API-KEY": api_key,
    }


def _request(
    method: str,
    api_base: str,
    api_key: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{api_base.rstrip('/')}{path}"
    resp = requests.request(method, url, headers=_headers(api_key), json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def load_flow() -> Dict[str, Any]:
    return json.loads(FLOW_FILE.read_text(encoding="utf-8"))


def list_workflows(api_base: str, api_key: str) -> List[Dict[str, Any]]:
    data = _request("GET", api_base, api_key, "/workflows?limit=250")
    items = data.get("data")
    return items if isinstance(items, list) else []


def upsert_workflow(
    api_base: str,
    api_key: str,
    flow: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = {
        "name": flow["name"],
        "nodes": flow["nodes"],
        "connections": flow["connections"],
        "settings": flow.get("settings") or {"executionOrder": "v1"},
        "staticData": flow.get("staticData"),
    }
    if existing and existing.get("id"):
        wf_id = str(existing["id"])
        print(f"Atualizando workflow existente: {wf_id}")
        return _request("PUT", api_base, api_key, f"/workflows/{wf_id}", payload)
    print("Criando workflow site-record Teams outbound")
    return _request("POST", api_base, api_key, "/workflows", payload)


def activate_workflow(api_base: str, api_key: str, workflow_id: str) -> None:
    _request("POST", api_base, api_key, f"/workflows/{workflow_id}/activate")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy fluxo n8n Teams outbound site-record")
    parser.add_argument("--dry-run", action="store_true", help="Só exibe URL esperada")
    args = parser.parse_args()

    n8n_url = _env("N8N_API_URL", DEFAULT_N8N_BASE)
    n8n_key = _env("N8N_API_KEY")
    webhook_base = _env("N8N_WEBHOOK_BASE_URL", n8n_url.replace("/api/v1", ""))
    expected_webhook = f"{webhook_base.rstrip('/')}/webhook/{WEBHOOK_PATH}"

    print("Fluxo:", FLOW_FILE.name)
    print("Webhook Django (N8N_TEAMS_WEBHOOK_URL):")
    print(f"  {expected_webhook}")
    print()
    print("Variáveis Railway site-record:")
    print(f"  N8N_TEAMS_WEBHOOK_URL={expected_webhook}")
    print("  SITE_URL=https://www.recordpap.com.br")
    print()
    print("Variável n8n (Settings → Variables):")
    print("  TEAMS_INCOMING_WEBHOOK_URL=<Incoming Webhook do canal Teams>")
    print()
    print("Como obter TEAMS_INCOMING_WEBHOOK_URL:")
    print("  1. No canal Teams desejado: ⋯ → Workflows → Post to channel when webhook request is received")
    print("  2. Copie a URL do Incoming Webhook gerada (NÃO use o link meetup-join do chat)")
    print()

    if args.dry_run:
        return 0

    if not n8n_key:
        print("Defina N8N_API_KEY para publicar o fluxo.", file=sys.stderr)
        return 1

    api_base = _api_base(n8n_url)
    flow = load_flow()
    existing = next((w for w in list_workflows(api_base, n8n_key) if w.get("name") == FLOW_NAME), None)
    saved = upsert_workflow(api_base, n8n_key, flow, existing)
    wf_id = str(saved.get("id") or (existing or {}).get("id") or "")
    if not wf_id:
        print("Workflow sem ID após upsert.", file=sys.stderr)
        return 1

    if not saved.get("active"):
        activate_workflow(api_base, n8n_key, wf_id)
        print(f"Workflow ativado: id={wf_id}")
    else:
        print(f"Workflow já ativo: id={wf_id}")

    print(f"\nConfigure no Railway: N8N_TEAMS_WEBHOOK_URL={expected_webhook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
