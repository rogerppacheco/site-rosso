#!/usr/bin/env python3
"""Migra templates HTML do frontend/public para extends base.html."""
from __future__ import annotations

import re
from pathlib import Path

SKIP_FILES = {
    "prevenda_publica.html",
    "teste-botoes-v13-1.html",
}


def should_skip_link(tag: str) -> bool:
    lower = tag.lower()
    if "bootstrap-icons" in lower:
        return True
    if "npm/bootstrap@" in lower and "bootstrap.min.css" in lower:
        return True
    if "custom_styles.css" in lower:
        return True
    if "fonts.googleapis.com" in lower or "fonts.gstatic.com" in lower:
        return True
    if "logo.png" in lower:
        return True
    return False


def should_skip_script(tag: str) -> bool:
    lower = tag.lower()
    if "bootstrap.bundle" in lower:
        return True
    if "theme-toggle.js" in lower:
        return True
    if re.search(r"menu\.js", lower) and "static" in lower:
        return True
    return False


def extract_title(content: str) -> str:
    match = re.search(r"<title>(.*?)</title>", content, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else "Record PAP"


def extract_head_extras(content: str) -> tuple[str, str, str]:
    head_match = re.search(r"<head[^>]*>(.*?)</head>", content, re.DOTALL | re.IGNORECASE)
    if not head_match:
        return "", "", ""

    head = head_match.group(1)
    extra_links: list[str] = []
    head_scripts: list[str] = []
    styles: list[str] = []

    for link in re.finditer(r"<link\b[^>]*>", head, re.IGNORECASE):
        tag = link.group(0)
        if "stylesheet" not in tag.lower():
            continue
        if should_skip_link(tag):
            continue
        extra_links.append(tag)

    for script in re.finditer(
        r"<script\b[^>]*src=[^>]+>\s*</script>",
        head,
        re.IGNORECASE,
    ):
        tag = script.group(0)
        if should_skip_script(tag):
            continue
        head_scripts.append(tag)

    for style in re.finditer(r"<style[^>]*>(.*?)</style>", head, re.DOTALL | re.IGNORECASE):
        body = style.group(1).strip()
        if body:
            styles.append(body)

    return "\n".join(extra_links), "\n".join(head_scripts), "\n\n".join(styles)


def extract_header_nav(content: str) -> str | None:
    match = re.search(
        r'<nav\s+class="main-nav"[^>]*>\s*<ul>(.*?)</ul>',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    lines = match.group(1).strip().splitlines()
    return "\n".join(f"    {line}" if line.strip() else line for line in lines)


def split_tail_scripts(chunk: str) -> tuple[str, list[str]]:
    """Separa bloco HTML do cluster de scripts finais (antes de </body>)."""
    body_close = chunk.rfind("</body>")
    if body_close != -1:
        chunk = chunk[:body_close]

    script_start = chunk.rfind("<script")
    if script_start == -1:
        return chunk.strip(), []

    html_part = chunk[:script_start].rstrip()
    scripts_blob = chunk[script_start:]
    scripts = re.findall(
        r"<script\b[^>]*>.*?</script\s*>",
        scripts_blob,
        re.DOTALL | re.IGNORECASE,
    )
    kept = [script for script in scripts if not should_skip_script(script)]
    return html_part.strip(), kept


def extract_body_parts(content: str) -> tuple[str, str, list[str]] | None:
    header_end = re.search(r"</header\s*>", content, re.IGNORECASE)
    if not header_end:
        return None

    after_header = content[header_end.end():]
    chunk = after_header

    footer_block = ""
    footer_match = re.search(r"(<footer\b.*?</footer\s*>)", chunk, re.DOTALL | re.IGNORECASE)
    if footer_match:
        footer_block = footer_match.group(1).strip()
        chunk = chunk[: footer_match.start()] + chunk[footer_match.end() :]

    main_content, scripts = split_tail_scripts(chunk)
    return main_content, footer_block, scripts


def needs_template_tags(*parts: str) -> bool:
    combined = "\n".join(parts)
    return any(token in combined for token in ("{% static", "{% url", "{% csrf", "{{ "))


def build_migrated_template(
    title: str,
    extra_links: str,
    head_scripts: str,
    extra_css: str,
    header_nav: str | None,
    main_content: str,
    footer_block: str,
    scripts: list[str],
) -> str:
    lines = ['{% extends "base.html" %}', ""]

    if needs_template_tags(main_content, footer_block, extra_css, "\n".join(scripts)):
        lines.extend(["{% load static %}", ""])

    lines.extend([f"{{% block title %}}{title}{{% endblock %}}", ""])

    if extra_links or head_scripts:
        lines.append("{% block extra_head %}")
        if extra_links:
            lines.append(extra_links)
        if head_scripts:
            lines.append(head_scripts)
        lines.append("{% endblock %}")
        lines.append("")

    if extra_css.strip():
        lines.extend(
            [
                "{% block extra_css %}",
                "<style>",
                extra_css.strip(),
                "</style>",
                "{% endblock %}",
                "",
            ]
        )

    if header_nav is not None:
        lines.extend(["{% block header_nav %}", header_nav, "{% endblock %}", ""])

    lines.extend(["{% block content %}", main_content, "{% endblock %}", ""])

    if footer_block:
        lines.extend(["{% block footer %}", footer_block, "{% endblock %}", ""])

    if scripts:
        lines.append("{% block extra_js %}")
        lines.extend(scripts)
        lines.append("{% endblock %}")
        lines.append("")

    return "\n".join(lines)


def migrate_file(path: Path) -> str:
    original = path.read_text(encoding="utf-8")
    if '{% extends "base.html" %}' in original:
        return "skipped"

    title = extract_title(original)
    extra_links, head_scripts, extra_css = extract_head_extras(original)
    header_nav = extract_header_nav(original)
    body_parts = extract_body_parts(original)
    if body_parts is None:
        return "failed"

    main_content, footer_block, scripts = body_parts
    migrated = build_migrated_template(
        title=title,
        extra_links=extra_links,
        head_scripts=head_scripts,
        extra_css=extra_css,
        header_nav=header_nav,
        main_content=main_content,
        footer_block=footer_block,
        scripts=scripts,
    )

    extracted_size = len(main_content) + len(footer_block) + sum(len(script) for script in scripts)
    if extracted_size < len(original) * 0.55:
        return "failed_size"

    path.write_text(migrated, encoding="utf-8", newline="\n")
    return "ok"


def patch_public_pages(root: Path) -> None:
    anti_flicker = """
    <script>
        (function () {
            var STORAGE_KEY = 'record-pap-theme';
            var stored = localStorage.getItem(STORAGE_KEY);
            var theme = stored;
            if (theme !== 'dark' && theme !== 'light') {
                theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            }
            document.documentElement.setAttribute('data-theme', theme);
            document.documentElement.style.colorScheme = theme;
            document.documentElement.style.backgroundColor = theme === 'dark' ? '#0F172A' : '#F7F9FC';
        })();
    </script>"""

    for name in SKIP_FILES:
        path = root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if "record-pap-theme" in content:
            continue

        if "<head>" in content:
            content = content.replace("<head>", "<head>\n" + anti_flicker, 1)

        content = re.sub(
            r"custom_styles\.css\?v=[^\"']+",
            "custom_styles.css?v=15.0",
            content,
        )
        if "custom_styles.css" not in content:
            if "{% load static %}" not in content:
                content = "{% load static %}\n" + content
            content = content.replace(
                "</head>",
                '    <link rel="stylesheet" href="{% static \'css/custom_styles.css\' %}?v=15.0">\n</head>',
                1,
            )

        if "theme-toggle.js" not in content:
            content = content.replace(
                "</body>",
                '    <script>(function(){var t=document.documentElement.getAttribute(\'data-theme\')||\'light\';document.body.setAttribute(\'data-theme\',t);})();</script>\n'
                '    <script src="{% static \'js/theme-toggle.js\' %}?v=1.0"></script>\n</body>',
                1,
            )

        path.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    root = Path("frontend/public")
    results: dict[str, list[str]] = {
        "ok": [],
        "skipped": [],
        "failed": [],
        "failed_size": [],
    }

    for path in sorted(root.glob("*.html")):
        if path.name in SKIP_FILES:
            continue
        status = migrate_file(path)
        results[status].append(path.name)

    patch_public_pages(root)

    for key, items in results.items():
        print(f"{key} ({len(items)}): {', '.join(items)}")


if __name__ == "__main__":
    main()
