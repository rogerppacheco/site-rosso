"""
Baixa CDOI #N da API de produção e gera o payload SmartRiser localmente.

Uso:
  set VTOP_PROD_TOKEN=<accessToken do localStorage em www.recordpap.com.br>
  .venv\\Scripts\\python.exe scripts\\sync_cdoi_prod_payload.py 21

Ou:
  .venv\\Scripts\\python.exe scripts\\sync_cdoi_prod_payload.py 21 --token SEU_TOKEN

Gera:
  tmp_vtop_payload_cdoi_21.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://www.recordpap.com.br"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync payload CDOI produção → JSON local")
    parser.add_argument("cdoi_id", type=int, help="ID do CDOI (ex.: 21)")
    parser.add_argument("--token", default=os.environ.get("VTOP_PROD_TOKEN", "").strip())
    parser.add_argument("--base-url", default=os.environ.get("VTOP_PROD_BASE_URL", DEFAULT_BASE_URL))
    args = parser.parse_args()

    if not args.token:
        print(
            "Informe o Bearer token.\n"
            "No Chrome (logado em recordpap): F12 → Application → Local Storage → accessToken\n"
            "Depois:\n"
            f"  $env:VTOP_PROD_TOKEN='...'\n"
            f"  .venv\\Scripts\\python.exe scripts\\sync_cdoi_prod_payload.py {args.cdoi_id}"
        )
        return 2

    url = f"{args.base_url.rstrip('/')}/api/crm/cdoi/editar/{args.cdoi_id}/"
    print(f"GET {url}")
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {args.token}", "Accept": "application/json"},
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"HTTP {resp.status_code}: {resp.text[:500]}")
        return 1

    data = resp.json()
    out_raw = BASE / f"tmp_vtop_cdoi_{args.cdoi_id}_raw.json"
    out_raw.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw salvo: {out_raw}")

    # Mesma lógica do serviço (sem Django model)
    blocos = data.get("blocos") or []
    nomes = [b.get("nome") or "" for b in blocos]
    max_andares = max((int(b.get("andares") or 0) for b in blocos), default=0)
    partes = []
    for b in blocos:
        partes.append(
            f"{b.get('nome')}: {b.get('andares')} andares, {b.get('aptos')} ums/andar "
            f"({b.get('total')} HPs)"
        )
    infra = (data.get("infraestrutura") or "").strip()
    if infra:
        partes.append(f"Infraestrutura: {infra}")
    partes.append(f"Shaft/DG: {'sim' if data.get('possui_shaft') else 'não'}")

    total_hps = sum(int(b.get("total") or 0) for b in blocos) or 0
    pre_venda = max(1, int(round(total_hps * 0.1))) if total_hps else 0

    payload = {
        "cdoi_id": data.get("id") or args.cdoi_id,
        "nome_condominio": (data.get("nome_condominio") or "").strip(),
        "nome_sindico": (data.get("nome_sindico") or "").strip(),
        "contato": "".join(ch for ch in str(data.get("contato") or "") if ch.isdigit()),
        "cep": "".join(ch for ch in str(data.get("cep") or "") if ch.isdigit()),
        "logradouro": (data.get("logradouro") or "").strip(),
        "numero": (data.get("numero") or "").strip(),
        "bairro": (data.get("bairro") or "").strip(),
        "cidade": (data.get("cidade") or "").strip(),
        "uf": (data.get("uf") or "").strip().upper(),
        "latitude": (data.get("latitude") or "").strip(),
        "longitude": (data.get("longitude") or "").strip(),
        "total_hps": total_hps,
        "pre_venda": pre_venda,
        "qtd_blocos": len(blocos),
        "max_andares": max_andares,
        "complemento": ", ".join(n for n in nomes if n),
        "caracteristicas": "; ".join(partes),
        "link_carta": data.get("link_carta_sindico") or "",
        "link_fachada": data.get("link_fotos_fachada") or "",
        "codigo_sap": "1068561",
        "cod_survey": "",
        "estacao": "",
        "celula": "",
        "cdoi_codigo": str(data.get("id") or args.cdoi_id),
        "blocos": blocos,
    }

    out_payload = BASE / f"tmp_vtop_payload_cdoi_{args.cdoi_id}.json"
    out_payload.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Payload SmartRiser: {out_payload}")
    print(
        f"Condomínio: {payload['nome_condominio']} | "
        f"{payload['cidade']}-{payload['uf']} | HPs={payload['total_hps']} | "
        f"carta={'sim' if payload['link_carta'] else 'não'} | "
        f"fachada={'sim' if payload['link_fachada'] else 'não'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
