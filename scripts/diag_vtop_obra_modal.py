"""Abre o modal Cadastro de nova obra e lista inputs/selects (ids/names)."""

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

from crm_app.services_vtop_smartriser import VTOP_SMARTRISER_URL, _storage_state_path

OUT = BASE / "tmp_vtop_dom_obra_modal.json"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=40)
        context = browser.new_context(storage_state=_storage_state_path(), locale="pt-BR")
        page = context.new_page()
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        time.sleep(1.5)
        try:
            page.get_by_text("Brownfield", exact=False).first.click(timeout=8000)
            time.sleep(1.5)
        except Exception:
            pass
        page.locator("#addUmaObra").click()
        page.get_by_text("Cadastro de nova obra").wait_for(state="visible", timeout=15000)
        time.sleep(0.5)
        data = page.evaluate(
            """() => {
              const root = document.body;
              const fields = Array.from(root.querySelectorAll('input, select, textarea')).map(el => {
                const label = (() => {
                  if (el.id) {
                    const l = document.querySelector(`label[for="${el.id}"]`);
                    if (l) return (l.innerText || '').trim();
                  }
                  const prev = el.previousElementSibling;
                  if (prev && /LABEL|SPAN|DIV|TD|TH/i.test(prev.tagName)) return (prev.innerText || '').trim().slice(0, 80);
                  const parent = el.parentElement;
                  if (parent) {
                    const t = (parent.innerText || '').trim().split('\\n')[0];
                    return t.slice(0, 80);
                  }
                  return '';
                })();
                const r = el.getBoundingClientRect();
                return {
                  tag: el.tagName,
                  type: el.type || '',
                  id: el.id || '',
                  name: el.name || '',
                  placeholder: el.placeholder || '',
                  label,
                  value: (el.value || '').slice(0, 60),
                  visible: !!(r.width && r.height && getComputedStyle(el).visibility !== 'hidden'),
                  options: el.tagName === 'SELECT' ? Array.from(el.options).slice(0, 20).map(o => ({v:o.value, t:o.text})) : undefined,
                };
              }).filter(f => f.visible);
              return { url: location.href, fields };
            }"""
        )
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(BASE / "tmp_vtop_obra_modal.png"))
        print("Campos:", len(data["fields"]))
        for f in data["fields"]:
            print(f"{f['tag']:6} id={f['id']!r:25} name={f['name']!r:20} label={f['label']!r}")
        print("Salvo", OUT)
        time.sleep(5)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
