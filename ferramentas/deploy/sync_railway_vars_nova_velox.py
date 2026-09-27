"""Copia variáveis essenciais do site-record para nova-velox (sem imprimir secrets)."""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

RAILWAY = r"C:\Users\rogge\AppData\Roaming\npm\railway.cmd"
ROOT = Path(r"C:\nova-velox")
PROJECT_ID = "7171eee1-2c6e-446a-b7a9-880d3786c51a"
ENVIRONMENT = "production"


def railway_json(*args: str) -> dict:
    cmd = [
        RAILWAY,
        *args,
        "-p",
        PROJECT_ID,
        "-e",
        ENVIRONMENT,
    ]
    out = subprocess.check_output(cmd, text=True, cwd=str(ROOT))
    return json.loads(out)


def railway_run(*args: str) -> None:
    cmd = [
        RAILWAY,
        *args,
        "-p",
        PROJECT_ID,
        "-e",
        ENVIRONMENT,
    ]
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> int:
    src = railway_json("variables", "--service", "site-record", "--json")
    copy_keys = [
        "DATABASE_URL",
        "DATABASE_UNPOOLED_URL",
        "PGBOUNCER_ENABLED",
        "DB_CONN_MAX_AGE",
        "EMAIL_BACKEND",
        "EMAIL_HOST",
        "EMAIL_PORT",
        "EMAIL_USE_TLS",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_PASSWORD",
        "DEFAULT_FROM_EMAIL",
        "CLOUDFLARE_R2_ACCOUNT_ID",
        "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "CLOUDFLARE_R2_PUBLIC_URL",
        "CAPTCHA_API_KEY",
        "CAPTCHA_PROVIDER",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
    ]
    pairs: list[str] = []
    for key in copy_keys:
        val = src.get(key)
        if val is not None and str(val) != "":
            pairs.append(f"{key}={val}")

    pairs.extend(
        [
            "POSTGRES_SCHEMA=nova_velox",
            "DEBUG=False",
            f"SECRET_KEY={secrets.token_urlsafe(50)}",
            "CLOUDFLARE_R2_BUCKET_NAME=nova-velox-midia",
            "R2_FOLDER_ROOT=NovaVelox",
            "EVOLUTION_INSTANCE_NAME=nova_velox_zap",
            "GUNICORN_WORKERS=2",
            "GUNICORN_THREADS=2",
            "WHATSAPP_WEBHOOK_ASYNC=True",
        ]
    )

    ok = 0
    for pair in pairs:
        key = pair.split("=", 1)[0]
        try:
            railway_run(
                "variable",
                "set",
                pair,
                "--service",
                "nova-velox",
                "--skip-deploys",
            )
            ok += 1
            print(f"SET {key}")
        except subprocess.CalledProcessError as exc:
            print(f"FAIL {key}: {exc}", file=sys.stderr)

    dst = railway_json("variables", "--service", "nova-velox", "--json")
    print("TOTAL_SET", ok, "/", len(pairs))
    print("POSTGRES_SCHEMA", dst.get("POSTGRES_SCHEMA"))
    print("HAS_DATABASE_URL", bool(dst.get("DATABASE_URL")))
    print("HAS_DATABASE_UNPOOLED_URL", bool(dst.get("DATABASE_UNPOOLED_URL")))
    return 0 if ok == len(pairs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
