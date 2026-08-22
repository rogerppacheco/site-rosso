"""
Publica .playwright_google_form_state.json no Railway (site-record-webhook)
como GOOGLE_FORM_STORAGE_STATE_B64.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".playwright_google_form_state.json"


def main() -> None:
    if not STATE.is_file():
        print(f"Arquivo não encontrado: {STATE}")
        print("Rode antes: python scripts/salvar_sessao_google_form.py")
        sys.exit(1)

    raw = STATE.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    print(f"Arquivo: {STATE} ({len(raw)} bytes) -> B64 {len(b64)} chars")

    # No Windows o CLI costuma ser railway.ps1 (PowerShell); subprocess direto falha.
    # Usar PowerShell garante o mesmo PATH do seu terminal.
    ps_cmd = (
        "railway variables set "
        "--service site-record-webhook "
        "--environment production "
        "'GOOGLE_FORM_STORAGE_STATE=/app/.playwright_google_form_state.json' "
        f"'GOOGLE_FORM_STORAGE_STATE_B64={b64}' "
        "'GOOGLE_FORM_LOGIN_EMAIL=roggerio@gmail.com'"
    )
    print("Atualizando variáveis no Railway...")
    try:
        subprocess.check_call(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
        )
    except FileNotFoundError:
        # Fallback Unix / railway no PATH
        railway = shutil.which("railway")
        if not railway:
            print("CLI 'railway' não encontrado. Instale: npm i -g @railway/cli")
            sys.exit(1)
        subprocess.check_call(
            [
                railway,
                "variables",
                "set",
                "--service",
                "site-record-webhook",
                "--environment",
                "production",
                "GOOGLE_FORM_STORAGE_STATE=/app/.playwright_google_form_state.json",
                f"GOOGLE_FORM_STORAGE_STATE_B64={b64}",
                "GOOGLE_FORM_LOGIN_EMAIL=roggerio@gmail.com",
            ]
        )

    print("OK — GOOGLE_FORM_STORAGE_STATE_B64 atualizado.")
    print("Aguarde o redeploy automático do webhook.")


if __name__ == "__main__":
    main()
