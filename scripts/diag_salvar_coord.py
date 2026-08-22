"""Testa salvar coordenadas: preenche #edit_lat/#edit_lon, Procurar, salvarCoordenada()."""
from __future__ import annotations

import json
import os
import re
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

LAT = "-19.868454"
LON = "-44.026851"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=60)
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
        # preenche mínimo para contexto
        page.locator("#sel_uf_obra").select_option("MG")
        time.sleep(0.5)
        page.locator("#input_localidade_abrev").evaluate(
            "(el,v)=>{el.removeAttribute('disabled'); el.value=v;}", "Contagem"
        )
        page.locator("#input_logradouro").fill("Rua Dezoito")
        page.locator("#input_num_fachada").fill("185")
        page.locator("#input_bairro").fill("Arvoredo 2ª Seção")
        page.locator("#input_complemento").fill("BLOCO 05")
        page.locator("#input_quantidade_ums").fill("16")

        before = page.evaluate(
            "() => ({span_lat: document.querySelector('#span_lat')?.innerText, span_lon: document.querySelector('#span_lon')?.innerText, input_lat: document.querySelector('#input_lat')?.value, input_lon: document.querySelector('#input_lon')?.value || document.querySelector('#input_lng')?.value})"
        )
        print("ANTES", before)

        page.locator('#lat_long a[onclick*="abrirMapa"], img[src*="icon_map.png"]').first.click()
        page.locator("#edit_lat").wait_for(state="visible", timeout=10000)
        page.locator("#edit_lat").fill(LAT)
        page.locator("#edit_lon").fill(LON)
        print("inputs", page.locator("#edit_lat").input_value(), page.locator("#edit_lon").input_value())

        page.locator("#b_map_procurar").click()
        time.sleep(2.5)

        # Inspeciona função/handler
        info = page.evaluate(
            """() => {
              const btn = document.querySelector('#b_salvar_coord');
              return {
                btn: btn ? {id: btn.id, value: btn.value, onclick: btn.getAttribute('onclick'), disabled: btn.disabled} : null,
                typeof_salvar: typeof salvarCoordenada,
                edit_lat: document.querySelector('#edit_lat')?.value,
                edit_lon: document.querySelector('#edit_lon')?.value,
              };
            }"""
        )
        print("INFO", json.dumps(info, ensure_ascii=False))

        # Tenta JS direto
        result = page.evaluate(
            """() => {
              try {
                if (typeof salvarCoordenada === 'function') {
                  salvarCoordenada();
                  return {ok: true, via: 'js'};
                }
                const btn = document.querySelector('#b_salvar_coord');
                if (btn) { btn.click(); return {ok: true, via: 'btn.click'}; }
                return {ok: false};
              } catch (e) {
                return {ok: false, error: String(e)};
              }
            }"""
        )
        print("SALVAR", result)
        time.sleep(2)

        after = page.evaluate(
            "() => ({span_lat: document.querySelector('#span_lat')?.innerText, span_lon: document.querySelector('#span_lon')?.innerText, input_lat: document.querySelector('#input_lat')?.value, input_lon: document.querySelector('#input_lon')?.value, mapa_visivel: !!(document.querySelector('#edit_lat') && document.querySelector('#edit_lat').offsetParent !== null)})"
        )
        print("DEPOIS", after)
        page.screenshot(path=str(BASE / "tmp_vtop_apos_salvar_coord.png"))
        print("Screenshot tmp_vtop_apos_salvar_coord.png")
        print("Browser aberto 60s para conferência…")
        time.sleep(60)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
