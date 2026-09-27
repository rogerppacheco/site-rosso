"""Cria workers nova-velox (webhook/pap/scheduler), copia vars e prepara deploy."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

RAILWAY = r"C:\Users\rogge\AppData\Roaming\npm\railway.cmd"
ROOT = Path(r"C:\nova-velox")
PROJECT = "d59e15a9-ac18-4561-876c-1f229b1ec91c"
ENV = "production"
WEB = "nova-velox"

WORKERS = {
    "nova-velox-webhook": {
        "toml": "railway.webhook.toml",
        "extra": {
            "WHATSAPP_WORKER_MODE": "True",
            "WHATSAPP_WEBHOOK_ASYNC": "False",
            "WHATSAPP_WORKER_POLL_SECONDS": "1",
            "WHATSAPP_USE_DEDICATED_WORKER": "True",
            "POSTGRES_SCHEMA": "nova_velox",
        },
    },
    "nova-velox-pap": {
        "toml": "railway.pap.toml",
        "extra": {
            "PAP_WORKER_MODE": "True",
            "PAP_WORKER_POLL_SECONDS": "2",
            "PAP_USE_DEDICATED_WORKER": "True",
            "PAP_SESSIONS_DIR": "/data/pap_sessions",
            "POSTGRES_SCHEMA": "nova_velox",
        },
    },
    "nova-velox-scheduler": {
        "toml": "railway.scheduler.toml",
        "extra": {
            "POSTGRES_SCHEMA": "nova_velox",
        },
    },
}


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [RAILWAY, *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=check,
    )


def vars_json(service: str) -> dict:
    out = run(
        ["variables", "--service", service, "-p", PROJECT, "-e", ENV, "--json"]
    ).stdout
    return json.loads(out)


def set_var(service: str, pair: str) -> None:
    run(
        [
            "variable",
            "set",
            pair,
            "--service",
            service,
            "-p",
            PROJECT,
            "-e",
            ENV,
            "--skip-deploys",
        ]
    )


def main() -> int:
    web = vars_json(WEB)
    base_pairs: list[str] = []
    for key, val in web.items():
        if key.startswith("RAILWAY_"):
            continue
        if val is None or val == "":
            continue
        base_pairs.append(f"{key}={val}")

    existing = {
        s.get("name")
        for s in json.loads(
            run(["service", "list", "-p", PROJECT, "-e", ENV, "--json"]).stdout
        )
    }
    print("EXISTING", sorted(existing))

    for name, cfg in WORKERS.items():
        if name not in existing:
            print("CREATE", name)
            run(["add", "--service", name, "--json"])
        else:
            print("EXISTS", name)

        print("COPY_VARS", name)
        for pair in base_pairs:
            set_var(name, pair)
            print(" ", pair.split("=", 1)[0])
        for key, val in cfg["extra"].items():
            set_var(name, f"{key}={val}")
            print(" EXTRA", key)

        dst = vars_json(name)
        assert dst.get("POSTGRES_SCHEMA") == "nova_velox", name
        assert dst.get("DATABASE_URL"), name
        print("OK_ISOLATION", name)

    # Flags no web para delegar aos workers
    for pair in (
        "PAP_USE_DEDICATED_WORKER=True",
        "WHATSAPP_USE_DEDICATED_WORKER=True",
        "WHATSAPP_WEBHOOK_ASYNC=True",
    ):
        set_var(WEB, pair)
        print("WEB", pair)

    print("DONE_SETUP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
