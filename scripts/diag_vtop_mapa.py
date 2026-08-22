"""Dump dos inputs do modal de mapa (Latitude/Longitude)."""
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

OUT = BASE / "tmp_vtop_dom_mapa.json"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=40)
        context = browser.new_context(storage_state=_storage_state_path(), locale="pt-BR")
        page = context.new_page()
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        time.sleep(1.5)
        try:
            page.get_by_text("Brownfield", exact=False).first.click(timeout=8000)
            time.sleep(1)
        except Exception:
            pass
        page.locator("#addUmaObra").click()
        page.get_by_text("Cadastro de nova obra").wait_for(state="visible", timeout=15000)
        time.sleep(0.5)
        page.locator('#lat_long a[onclick*="abrirMapa"], img[src*="icon_map.png"]').first.click()
        page.get_by_text(re.compile(r"Latitude", re.I)).first.wait_for(state="visible", timeout=10000)
        time.sleep(0.5)

        data = page.evaluate(
            """() => {
              const all = Array.from(document.querySelectorAll('input, button, select, textarea'));
              const items = all.map(el => {
                const r = el.getBoundingClientRect();
                const cs = getComputedStyle(el);
                return {
                  tag: el.tagName,
                  type: el.type || '',
                  id: el.id || '',
                  name: el.name || '',
                  value: (el.value || '').slice(0, 40),
                  placeholder: el.placeholder || '',
                  className: (el.className || '').toString().slice(0, 120),
                  text: (el.innerText || el.value || '').toString().slice(0, 40),
                  visible: !!(r.width && r.height && cs.visibility !== 'hidden' && cs.display !== 'none'),
                  disabled: !!el.disabled,
                  rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                };
              }).filter(i => i.visible);
              // labels próximos
              const labels = Array.from(document.querySelectorAll('label, td, th, span, div'))
                .filter(el => /Latitude|Longitude|Procurar|Salvar|Cancelar/i.test(el.innerText || ''))
                .slice(0, 40)
                .map(el => ({
                  tag: el.tagName,
                  id: el.id || '',
                  text: (el.innerText || '').trim().slice(0, 80),
                }));
              return { url: location.href, items, labels, html: document.body.innerHTML.slice(0, 8000) };
            }"""
        )
        # need re in evaluate scope - used wait above with re - import re
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(BASE / "tmp_vtop_mapa_modal.png"))
        print("Visíveis:", len(data["items"]))
        for i in data["items"]:
            if i["tag"] in ("INPUT", "BUTTON") or "lat" in i["id"].lower() or "lon" in i["id"].lower():
                print(i)
        print("Salvo", OUT)
        time.sleep(3)
        browser.close()
    return 0


if __name__ == "__main__":
    import re
    raise SystemExit(main())
