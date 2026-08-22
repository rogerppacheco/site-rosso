"""Executa sincronização de gravações de auditoria para R2 (uso com variáveis de produção)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _carregar_env_railway() -> None:
    result = subprocess.run(
        ["railway", "variables", "--json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_ROOT,
    )
    data = __import__("json").loads(result.stdout)
    for key, value in data.items():
        os.environ[key] = str(value)


def main() -> None:
    _carregar_env_railway()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

    import django

    django.setup()
    from django.core.management import call_command

    call_command(
        "sincronizar_gravacoes_auditoria_r2",
        lote=40,
        pausa=0.15,
    )


if __name__ == "__main__":
    main()
