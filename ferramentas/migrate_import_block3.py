#!/usr/bin/env python3
"""Migra templates importar_* do bloco 3 para core/templates com tokens de tema."""
from __future__ import annotations

import re
from pathlib import Path

FILES = [
    "importar_fpd.html",
    "importar_legado.html",
    "importar_mapa.html",
    "importar_osab.html",
    "importar_recompra.html",
]

THEME_CSS = """
        .importar-page .bg-white { background-color: var(--bg-card) !important; }
        .importar-page .bg-light { background-color: var(--bg-secondary) !important; }
        .importar-page .text-dark { color: var(--text-primary) !important; }
        .importar-page .info-card,
        .importar-page .upload-zone,
        .importar-page .progress-container,
        .importar-page .filter-card { border: 1px solid var(--border-color); color: var(--text-primary); }
"""

AUTH_MENU_SCRIPTS = (
    '<script src="{% static \'js/auth.js\' %}?v=7.0"></script>\n'
    '<script src="{% static \'js/menu.js\' %}?v=7.0"></script>\n'
)


def migrate_content(content: str) -> str:
    content = re.sub(
        r"\s*body\s*\{\s*background-color:\s*#f8f9fc;\s*\}\s*\n",
        "\n",
        content,
    )

    for old, new in (
        ("background: white;", "background: var(--bg-card);"),
        ("background: #f8f9fc;", "background: var(--bg-secondary);"),
        ("color: #858796;", "color: var(--text-secondary);"),
        ("color: #555;", "color: var(--text-secondary);"),
        ("color: #666;", "color: var(--text-secondary);"),
    ):
        content = content.replace(old, new)

    if ".importar-page" not in content:
        content = content.replace("</style>", f"{THEME_CSS}\n</style>", 1)

    content = content.replace(
        '<div class="import-container">',
        '<main class="importar-page"><div class="import-container">',
        1,
    )

    content = content.replace('class="info-card"', 'class="info-card card-modern"')
    content = content.replace('class="upload-zone"', 'class="upload-zone card-modern"')
    content = content.replace(
        'class="progress-container',
        'class="progress-container card-modern',
    )
    content = content.replace('class="filter-card"', 'class="filter-card card-modern"')

    content = re.sub(
        r'\n    <script src="https://cdn\.jsdelivr\.net/npm/bootstrap@5\.3\.3/dist/js/bootstrap\.bundle\.min\.js"></script>\n',
        "\n",
        content,
    )

    content = re.sub(
        r'\n    <script src="\{% static \'js/auth\.js\'[^>]*\}"></script>\s*\n'
        r'    <script src="\{% static \'js/menu\.js\'[^>]*\}"></script>\s*\n',
        "\n",
        content,
    )

    if "{% static " in content and "{% load static %}" not in content:
        content = content.replace(
            '{% extends "base.html" %}\n',
            '{% extends "base.html" %}\n\n{% load static %}\n',
            1,
        )

    content = re.sub(
        r"(\{% block extra_js %\}\n)(<script>)",
        rf"\1{AUTH_MENU_SCRIPTS}\2",
        content,
        count=1,
    )

    # Fecha <main> antes do fim do bloco content (spinner overlay fica dentro do main)
    content = re.sub(
        r"(\{% block content %\}[\s\S]*?)(\n{% endblock %}\n\n{% block extra_js %})",
        lambda m: _close_main(m.group(1)) + m.group(2),
        content,
        count=1,
    )

    return content


def _close_main(block_content: str) -> str:
    if "</main>" in block_content:
        return block_content
    return block_content.rstrip() + "\n</main>\n"


def main() -> None:
    root = Path("frontend/public")
    dest = Path("core/templates")
    for name in FILES:
        src = root / name
        text = migrate_content(src.read_text(encoding="utf-8"))
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"migrated: {name}")


if __name__ == "__main__":
    main()
