"""
Publica .playwright_vtop_state.json no Railway (site-record + scheduler)
como VTOP_STORAGE_STATE_B64.

Fluxo:
  1. Local: .venv\\Scripts\\python.exe scripts\\teste_login_vtop.py
     (abre browser, login V.tal, salva .playwright_vtop_state.json)
  2. Este script: publica o JSON em base64 nas variáveis Railway.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".playwright_vtop_state.json"
SERVICES = ("site-record", "site-record-scheduler")


def _set_vars(service: str, b64: str) -> None:
    pairs = [
        "VTOP_STORAGE_STATE=/app/.playwright_vtop_state.json",
        f"VTOP_STORAGE_STATE_B64={b64}",
        "VTOP_HEADLESS=true",
    ]
    railway = shutil.which("railway")
    if not railway:
        # Windows: railway.ps1 via PowerShell
        for i, pair in enumerate(pairs):
            skip = "--skip-deploys" if i < len(pairs) - 1 else ""
            cmd = (
                f"railway variable set --service {service} {skip} '{pair}'"
            ).strip()
            print(">", cmd[:120], "...")
            subprocess.check_call(["powershell", "-NoProfile", "-Command", cmd])
        return

    for i, pair in enumerate(pairs):
        args = [railway, "variable", "set", pair, "--service", service]
        if i < len(pairs) - 1:
            args.append("--skip-deploys")
        print(">", " ".join(args[:5]), "...")
        subprocess.check_call(args)


def main() -> int:
    if not STATE.is_file() or STATE.stat().st_size < 50:
        print(f"Arquivo inválido/ausente: {STATE}")
        print("Rode antes: .venv\\Scripts\\python.exe scripts\\teste_login_vtop.py")
        return 1

    raw = STATE.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    print(f"Arquivo: {STATE} ({len(raw)} bytes) -> B64 {len(b64)} chars")

    for svc in SERVICES:
        print(f"\n=== Publicando em {svc} ===")
        _set_vars(svc, b64)

    print("\nOK — VTOP_STORAGE_STATE_B64 atualizado.")
    print("Aguarde o redeploy. Depois o botão SmartRiser usa a sessão sem pedir senha na tela.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
