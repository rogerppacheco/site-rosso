"""Diagnóstico: abre Brownfield com sessão salva e lista botões/FABs candidatos a '+'."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from playwright.sync_api import sync_playwright

from crm_app.services_vtop_smartriser import (  # noqa: E402
    VTOP_HOME_URL,
    VTOP_SMARTRISER_URL,
    _storage_state_path,
)

OUT = BASE / "tmp_vtop_dom_brownfield.json"


def main() -> int:
    storage = _storage_state_path()
    if not Path(storage).exists():
        print("Sem sessão:", storage)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(storage_state=storage, locale="pt-BR")
        page = context.new_page()
        page.goto(VTOP_HOME_URL, wait_until="domcontentloaded")
        time.sleep(1)
        # Vai direto ao smartriser
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        time.sleep(2)
        # Tenta clicar Brownfield
        try:
            page.get_by_text("Brownfield", exact=False).first.click(timeout=8000)
            time.sleep(2)
        except Exception as exc:
            print("Brownfield click:", exc)

        # Captura candidatos
        data = page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll('a, button, [role=button], i, span, div'));
              const interesting = [];
              for (const el of nodes) {
                const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                const cls = el.className && el.className.toString ? el.className.toString() : '';
                const id = el.id || '';
                const tag = el.tagName;
                const aria = el.getAttribute('aria-label') || '';
                const title = el.getAttribute('title') || '';
                const href = el.getAttribute('href') || '';
                const onclick = el.getAttribute('onclick') || '';
                const style = (el.getAttribute('style') || '') + ' ' + (getComputedStyle(el).position || '');
                const looksFab =
                  text === '+' ||
                  text === '＋' ||
                  /fab|floating|add|plus|novo|incluir/i.test(cls + ' ' + id + ' ' + aria + ' ' + title + ' ' + href + ' ' + onclick) ||
                  (getComputedStyle(el).position === 'fixed' && (tag === 'A' || tag === 'BUTTON' || tag === 'DIV'));
                if (!looksFab) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                interesting.push({
                  tag, id, cls: cls.slice(0, 200), text: text.slice(0, 80),
                  aria, title, href: href.slice(0, 120), onclick: onclick.slice(0, 120),
                  position: getComputedStyle(el).position,
                  rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                });
              }
              return {
                url: location.href,
                title: document.title,
                fixed: interesting,
                html_snip: document.body ? document.body.innerHTML.slice(0, 5000) : '',
              };
            }"""
        )
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("URL:", data.get("url"))
        print("Candidatos:", len(data.get("fixed") or []))
        for i, item in enumerate(data.get("fixed") or []):
            print(f"{i:02d}", item)
        print("Salvo em", OUT)
        page.screenshot(path=str(BASE / "tmp_vtop_brownfield.png"), full_page=True)
        print("Screenshot: tmp_vtop_brownfield.png")
        time.sleep(8)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
