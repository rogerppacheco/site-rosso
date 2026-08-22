"""
Diagnóstico: abre o form com sessão salva e inspeciona dropdowns
(Executivo, Empresa, UF) — sem enviar.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["PAP_HEADLESS"] = "false"
os.environ["DEBUG_INCLUSAO_FORM"] = "1"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decouple import config as env_config

for key in ("GOOGLE_FORM_EMAIL", "GOOGLE_FORM_PASSWORD"):
    val = env_config(key, default="")
    if val and key not in os.environ:
        os.environ[key] = str(val)

import django

django.setup()

from django.conf import settings

settings.PAP_HEADLESS = False

from playwright.sync_api import sync_playwright

from crm_app.services_inclusao_viabilidade import (
    FORM_URL,
    _caminho_storage_state,
    _esta_no_formulario,
    _selecionar_dropdown,
)

EXECUTIVO = "ROGERIO PEREIRA PACHECO"
EMPRESA = "RECORD"
UF = "Minas Gerais"


def _dump_listboxes(page) -> list:
    """Extrai estado dos listboxes / triggers do Google Forms."""
    return page.evaluate(
        """() => {
        const out = [];
        // Triggers fechados: spans "Escolher" / valores selecionados
        document.querySelectorAll('div[role="listbox"]').forEach((lb, i) => {
            const txt = (lb.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 200);
            const aria = lb.getAttribute('aria-expanded');
            const opts = [...lb.querySelectorAll('[role="option"]')].map(o => ({
                text: (o.innerText || '').trim().slice(0, 80),
                value: o.getAttribute('data-value'),
                selected: o.getAttribute('aria-selected'),
            }));
            out.push({kind: 'listbox', i, aria, txt, optsCount: opts.length, opts: opts.slice(0, 8)});
        });
        // Fallback: spans Escolher
        document.querySelectorAll('span').forEach((sp) => {
            const t = (sp.innerText || '').trim();
            if (t === 'Escolher' || t === 'Selecione' || /^ROGERIO|^RECORD|^Minas/.test(t)) {
                // só anotar se parecer trigger de dropdown
                const cls = sp.className || '';
                if (cls.includes('vRMGwf') || cls.includes('oJeWuf') || t === 'Escolher') {
                    out.push({kind: 'span', text: t, cls: cls.slice(0, 60)});
                }
            }
        });
        return out;
    }"""
    )


def main() -> None:
    state = _caminho_storage_state()
    print("Storage:", state, "existe=", os.path.isfile(state))
    if not os.path.isfile(state):
        print("Sem sessão. Rode salvar_sessao_google_form.py primeiro.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(
            storage_state=state,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        if not _esta_no_formulario(page):
            print("Formulário não abriu. URL:", page.url)
            browser.close()
            sys.exit(1)

        print("\n=== ANTES das seleções ===")
        antes = _dump_listboxes(page)
        print(json.dumps(antes, ensure_ascii=False, indent=2))

        print("\n=== Chamando _selecionar_dropdown(EXECUTIVO, 0) ===")
        ok0 = _selecionar_dropdown(page, EXECUTIVO, 0)
        page.wait_for_timeout(800)
        print("retorno:", ok0)

        print("\n=== Chamando _selecionar_dropdown(EMPRESA, 1) ===")
        ok1 = _selecionar_dropdown(page, EMPRESA, 1)
        page.wait_for_timeout(800)
        print("retorno:", ok1)

        print("\n=== Chamando _selecionar_dropdown(UF, 2) ===")
        ok2 = _selecionar_dropdown(page, UF, 2)
        page.wait_for_timeout(800)
        print("retorno:", ok2)

        print("\n=== DEPOIS das seleções ===")
        depois = _dump_listboxes(page)
        print(json.dumps(depois, ensure_ascii=False, indent=2))

        print("\n=== Verificação visual (texto dos listboxes) ===")
        for lb in depois:
            if lb.get("kind") == "listbox":
                print(f"  listbox[{lb['i']}] expanded={lb.get('aria')} texto={lb.get('txt')!r}")

        print("\nJanela fica aberta 20s para você conferir os dropdowns...")
        page.wait_for_timeout(20000)
        browser.close()


if __name__ == "__main__":
    main()
