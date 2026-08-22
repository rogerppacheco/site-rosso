"""Gera baseline_sysr.sql e baseline_syncwa.sql via prisma migrate diff."""
from __future__ import annotations

import subprocess
from pathlib import Path

_BASE = Path(__file__).resolve().parent
TARGETS = {
    "sysr": Path(r"C:\sysr_vendas\backend"),
    "syncwa": Path(r"C:\SyncWA"),
}


def gerar(nome: str, repo: Path) -> None:
    result = subprocess.run(
        [
            "npx",
            "prisma",
            "migrate",
            "diff",
            "--from-empty",
            "--to-schema-datamodel",
            "prisma/schema.prisma",
            "--script",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        shell=True,
    )
    sql = result.stdout.strip() + "\n"
    out = _BASE / f"baseline_{nome}.sql"
    out.write_text(sql, encoding="utf-8")
    print(f"OK: {out} ({len(sql.splitlines())} linhas)")


def main() -> None:
    for nome, repo in TARGETS.items():
        if not repo.exists():
            print(f"PULADO: {repo}")
            continue
        gerar(nome, repo)


if __name__ == "__main__":
    main()
