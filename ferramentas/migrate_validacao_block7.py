#!/usr/bin/env python3
"""Migra templates validacao-* (bloco 7) para core/templates com tokens de tema."""
from __future__ import annotations

import re
from pathlib import Path

FILES = [
    "validacao-agendamento.html",
    "validacao-churn.html",
    "validacao-dfv.html",
    "validacao-fpd.html",
    "validacao-legado.html",
    "validacao-osab.html",
    "validacao-recompra.html",
]

THEME_CSS = """
        .validacao-page .bg-white { background-color: var(--bg-card) !important; }
        .validacao-page .bg-light { background-color: var(--bg-secondary) !important; }
        .validacao-page .text-dark { color: var(--text-primary) !important; }
        .validacao-page .btn-refresh { background: var(--accent-primary); color: var(--text-on-accent); }
"""

AUTH_MENU_SCRIPTS = (
    '<script src="{% static \'js/auth.js\' %}?v=7.0"></script>\n'
    '<script src="{% static \'js/menu.js\' %}?v=7.0"></script>\n'
)


def migrate_content(content: str) -> str:
    content = re.sub(
        r"\s*body\s*\{\s*background-color:\s*#f8f9fc;\s*padding-top:\s*80px;\s*\}\s*\n",
        "\n",
        content,
    )

    for old, new in (
        ("background: white;", "background: var(--bg-card);"),
        ("background: #f8f9fc;", "background: var(--bg-secondary);"),
        ("background-color: #f8f9fc;", "background-color: var(--bg-secondary);"),
        ("color: #858796;", "color: var(--text-secondary);"),
        ("background: #4e73df;", "background: var(--accent-primary);"),
    ):
        content = content.replace(old, new)

    if ".validacao-page" not in content:
        content = content.replace("</style>", f"{THEME_CSS}\n</style>", 1)

    content = content.replace(
        '<div class="validation-container">',
        '<div class="validation-container validacao-page">',
        1,
    )

    content = re.sub(
        r'class="stat-card ',
        'class="stat-card card-modern ',
        content,
    )
    content = content.replace(
        'class="filters-card"',
        'class="filters-card card-modern"',
    )
    content = content.replace(
        'class="logs-table-card"',
        'class="logs-table-card card-modern"',
    )

    content = re.sub(
        r'\n    <script src="\{% static \'js/auth\.js\'[^"]*"></script>\s*\n'
        r'    <script src="\{% static \'js/menu\.js\'[^"]*"></script>\s*\n'
        r'(\{% endblock %\}\n\n\{% block extra_js %\})',
        r"\n\1",
        content,
    )

    content = re.sub(
        r"(\{% block extra_js %\}\n)(<script>)",
        rf"\1{AUTH_MENU_SCRIPTS}\2",
        content,
        count=1,
    )

    return content


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
