"""Aplica @@schema nos arquivos schema.prisma (sysr / syncwa)."""
from __future__ import annotations

import re
from pathlib import Path

TARGETS = {
    Path(r"C:\sysr_vendas\backend\prisma\schema.prisma"): "sysr",
    Path(r"C:\SyncWA\prisma\schema.prisma"): "syncwa",
}


def _patch_datasource(content: str, schema: str) -> str:
    pattern = (
        r"datasource db \{\n"
        r"  provider = \"postgresql\"\n"
        r"  url      = env\(\"DATABASE_URL\"\)\n"
        r"\}"
    )
    replacement = (
        "datasource db {\n"
        "  provider = \"postgresql\"\n"
        "  url      = env(\"DATABASE_URL\")\n"
        f"  schemas  = [\"{schema}\"]\n"
        "}"
    )
    if f'schemas  = ["{schema}"]' in content:
        return content
    return re.sub(pattern, replacement, content, count=1)


def _patch_blocks(content: str, schema: str) -> str:
    lines = content.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("enum ") or line.startswith("model "):
            block: list[str] = [line]
            i += 1
            while i < len(lines) and not (
                lines[i].startswith("enum ") or lines[i].startswith("model ") or lines[i].startswith("// ───")
            ):
                if lines[i].strip() == "}" and not any("@@schema" in b for b in block):
                    block.append(f'  @@schema("{schema}")')
                block.append(lines[i])
                i += 1
                if block[-1].strip() == "}":
                    break
            out.extend(block)
            continue
        out.append(line)
        i += 1
    return "\n".join(out) + "\n"


def main() -> None:
    for path, schema in TARGETS.items():
        if not path.exists():
            print(f"PULADO (nao encontrado): {path}")
            continue
        original = path.read_text(encoding="utf-8")
        patched = _patch_datasource(original, schema)
        patched = _patch_blocks(patched, schema)
        path.write_text(patched, encoding="utf-8")
        print(f"OK: {path} -> schema {schema}")


if __name__ == "__main__":
    main()
