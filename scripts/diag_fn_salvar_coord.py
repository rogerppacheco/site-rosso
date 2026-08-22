"""Extrai o código-fonte de salvarCoordenada / procurar do SmartRiser."""
from __future__ import annotations

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

OUT = BASE / "tmp_vtop_salvar_coordenada.js"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=_storage_state_path(), locale="pt-BR")
        page = context.new_page()
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        time.sleep(2)
        try:
            page.get_by_text("Brownfield", exact=False).first.click(timeout=8000)
            time.sleep(1)
        except Exception:
            pass
        # abre mapa para garantir scripts carregados
        page.locator("#addUmaObra").click()
        time.sleep(1)
        page.locator('img[src*="icon_map.png"]').first.click()
        time.sleep(1)

        src = page.evaluate(
            """() => {
              const names = ['salvarCoordenada', 'procurarEndereco', 'procurarCoordenada', 'abrirMapa', 'atualizaLatLong'];
              const out = {};
              for (const n of names) {
                try { out[n] = (typeof window[n] === 'function') ? String(window[n]) : typeof window[n]; }
                catch(e) { out[n] = 'err:'+e; }
              }
              // procura scripts com salvarCoordenada
              const scripts = Array.from(document.scripts).map(s => s.src || '').filter(Boolean);
              out.script_srcs = scripts;
              return out;
            }"""
        )
        OUT.write_text(
            "\n\n".join(f"// ===== {k} =====\n{v}" for k, v in src.items() if k != "script_srcs")
            + "\n\n// scripts\n"
            + "\n".join(src.get("script_srcs") or []),
            encoding="utf-8",
        )
        print("Salvo", OUT)
        for k, v in src.items():
            if k == "script_srcs":
                print("scripts:", len(v))
                for s in v[:30]:
                    print(" ", s)
            else:
                print("====", k, "====")
                print(str(v)[:2000])
                print()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
