"""White-label: substitui marca Record → Nova Velox (texto de UI, sem quebrar models)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"C:\nova-velox")

SKIP_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "node_modules",
    "staticfiles",
    "media",
    "backups",
    "migrations",  # não reescrever 0001_initial já aplicadas
}

# Ordem: mais específico primeiro
REPLACEMENTS: list[tuple[str, str]] = [
    ("NOVA VELOX", "NOVA VELOX"),
    ("Nova Velox", "Nova Velox"),
    ("nova velox", "nova velox"),
    ("Nova Velox", "Nova Velox"),
    ("nova-velox", "nova-velox"),
    ("nova_velox", "nova_velox"),
    ("{{ SITE_BRAND_NAME }} Informa", "{{ SITE_BRAND_NAME }} Informa"),
    ("{{ SITE_BRAND_NAME }} Apoia", "{{ SITE_BRAND_NAME }} Apoia"),
    ("{{ SITE_BRAND_NAME }} Vertical", "{{ SITE_BRAND_NAME }} Vertical"),
    ("{{ SITE_BRAND_NAME }} Vendas", "{{ SITE_BRAND_NAME }} Vendas"),
    ("NovaVelox", "NovaVelox"),
    ("nova-velox", "nova-velox"),
    ("novavelox", "novavelox"),
    ("NovaVelox_CDOI", "NovaVelox_CDOI"),
]

# Em arquivos de código, "Record" sozinho só em contextos de UI conhecidos
UI_ONLY_GLOBS = {
    ".html",
    ".js",
    ".css",
    ".json",
    ".md",
    ".txt",
}

# Não tocar nestes arquivos (isolamento / deploy scripts)
SKIP_FILES = {
    "database.py",
    "criar_schema_nova_velox.py",
    "validar_isolamento_nova_velox.py",
    "00_criar_schema_nova_velox.sql",
    "sync_railway_vars_nova_velox.py",
    "_vars_backup.json",
}


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return True
    if path.name in SKIP_FILES:
        return True
    if path.suffix.lower() not in {
        ".py",
        ".html",
        ".js",
        ".css",
        ".json",
        ".md",
        ".txt",
        ".toml",
        ".yml",
        ".yaml",
        ".sh",
        ".example",
    }:
        return True
    return False


def transform(content: str, path: Path) -> str:
    out = content
    for old, new in REPLACEMENTS:
        out = out.replace(old, new)

    # Títulos / defaults de UI com "Record" isolado
    if path.suffix.lower() in UI_ONLY_GLOBS or path.name.endswith(".html"):
        out = out.replace(" - Record{", " - Nova Velox{")
        out = re.sub(r"(?<=[\s\"'>])Record(?=[\s\"'<!,.:;-]|$)", "Nova Velox", out)
        # Corrige duplicações acidentais
        out = out.replace("Nova Velox PAP", "Nova Velox")
        out = out.replace("Nova Velox Velox", "Nova Velox")

    # Python: strings de mensagem comuns
    if path.suffix == ".py":
        out = out.replace("do Nova Velox", "da Nova Velox")
        out = out.replace("especialista de qualidade do Nova Velox", "especialista de qualidade da Nova Velox")
        out = out.replace('or "Nova Velox"', 'or "Nova Velox"')
        out = out.replace("or 'Nova Velox'", "or 'Nova Velox'")
        out = out.replace('"Nova Velox"', '"Nova Velox"')
        out = out.replace("'Nova Velox'", "'Nova Velox'")
        # verbose_name / textos
        out = out.replace("Comunicado ({{ SITE_BRAND_NAME }} Informa)", "Comunicado ({{ SITE_BRAND_NAME }} Informa)")
        out = out.replace("Grupo WhatsApp (ex: Nova Velox)", "Grupo WhatsApp (ex: Nova Velox)")
        out = out.replace("Arquivo {{ SITE_BRAND_NAME }} Apoia", "Arquivo {{ SITE_BRAND_NAME }} Apoia")
        out = out.replace("Arquivos {{ SITE_BRAND_NAME }} Apoia", "Arquivos {{ SITE_BRAND_NAME }} Apoia")
        out = out.replace("Repositório de arquivos {{ SITE_BRAND_NAME }} Apoia", "Repositório de arquivos {{ SITE_BRAND_NAME }} Apoia")
        out = out.replace("User-Agent': 'NovaVelox/1.0'", "User-Agent': 'NovaVelox/1.0'")
        out = out.replace('User-Agent": "NovaVelox/1.0"', 'User-Agent": "NovaVelox/1.0"')
        out = out.replace("1068561 - NOVA VELOX", "1068561 - NOVA VELOX")
        out = out.replace("'Nova Velox',", "'Nova Velox',")
        out = out.replace('"Nova Velox",', '"Nova Velox",')

    return out


def main() -> None:
    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = transform(text, path)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print(f"OK {path.relative_to(ROOT)}")
    print(f"TOTAL_CHANGED {changed}")


if __name__ == "__main__":
    main()
