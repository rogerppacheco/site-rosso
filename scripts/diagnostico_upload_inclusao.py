"""
Diagnóstico do upload de arquivo no Google Forms (Inclusão).
Abre o form com sessão salva e tenta estratégias de upload.
"""
from __future__ import annotations

import os
import sys
import time
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
)

FOTO = ROOT / "scripts" / "_teste_inclusao_foto.jpg"


def main() -> None:
    state = _caminho_storage_state()
    assert FOTO.is_file(), f"Crie a foto de teste: {FOTO}"
    print("Foto:", FOTO, FOTO.stat().st_size, "bytes")
    print("State:", state)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        assert _esta_no_formulario(page), page.url

        # Scroll até a área de arquivo
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)

        print("\n=== inputs type=file na página ===")
        files = page.locator('input[type="file"]')
        print("count=", files.count())
        for i in range(files.count()):
            el = files.nth(i)
            print(
                i,
                "visible=",
                el.is_visible(),
                "name=",
                el.get_attribute("name"),
                "accept=",
                el.get_attribute("accept"),
            )

        print("\n=== botões Adicionar arquivo ===")
        for sel in [
            'text=Adicionar arquivo',
            'span:has-text("Adicionar arquivo")',
            'div[role="button"]:has-text("Adicionar arquivo")',
        ]:
            loc = page.locator(sel)
            print(sel, "count=", loc.count())

        btn = page.get_by_text("Adicionar arquivo", exact=False).first
        if btn.count() == 0:
            print("Botão Adicionar arquivo NÃO encontrado")
            page.wait_for_timeout(10000)
            browser.close()
            return

        print("\nClicando Adicionar arquivo...")
        btn.scroll_into_view_if_needed()
        btn.click()
        page.wait_for_timeout(3000)

        print("iframes:", page.locator("iframe").count())
        for i in range(page.locator("iframe").count()):
            fr = page.locator("iframe").nth(i)
            print(i, "src=", (fr.get_attribute("src") or "")[:120])

        # Procurar file inputs em todos os frames
        print("\n=== file inputs em frames ===")
        for idx, frame in enumerate(page.frames):
            try:
                n = frame.locator('input[type="file"]').count()
            except Exception as e:
                print(idx, frame.url[:60], "erro", e)
                continue
            if n:
                print(idx, "url=", frame.url[:80], "files=", n)
                for j in range(n):
                    fi = frame.locator('input[type="file"]').nth(j)
                    try:
                        print(
                            "  ",
                            j,
                            "vis=",
                            fi.is_visible(),
                            "name=",
                            fi.get_attribute("name"),
                        )
                    except Exception:
                        pass

        # Tentar set_input_files no primeiro file de qualquer frame
        ok = False
        for frame in page.frames:
            fi = frame.locator('input[type="file"]')
            if fi.count() == 0:
                continue
            try:
                print("Tentando set_input_files em", frame.url[:70])
                fi.first.set_input_files(str(FOTO), timeout=8000)
                ok = True
                print("OK set_input_files")
                break
            except Exception as e:
                print("falhou:", e)

        if not ok:
            # Clicar Procurar e capturar filechooser
            print("\nTentando Procurar + filechooser...")
            try:
                picker = page.frame_locator('iframe[src*="picker"], iframe[src*="docs.google.com"]')
                # listar textos no picker
                for texto in ["Procurar", "Browse", "Upload", "Fazer upload", "Meu Drive"]:
                    c = picker.locator(f'text={texto}').count()
                    print(f"  picker text '{texto}' count={c}")
                with page.expect_file_chooser(timeout=15000) as fc_info:
                    for sel in [
                        'text=Procurar',
                        'text=Browse',
                        '[jsname="V67aGc"]',
                        'button:has-text("Procurar")',
                    ]:
                        b = picker.locator(sel).first
                        if b.count() > 0:
                            print("clicando", sel)
                            b.click(force=True)
                            break
                fc = fc_info.value
                fc.set_files(str(FOTO))
                ok = True
                print("OK filechooser")
            except Exception as e:
                print("filechooser falhou:", e)

        page.wait_for_timeout(4000)
        print("\nResultado upload ok=", ok)
        # Indícios de arquivo anexado
        for t in ["1 arquivo", "arquivo", ".jpg", "teste_inclusao", "Remover"]:
            c = page.locator(f"text={t}").count()
            if c:
                print(f"  encontrado texto '{t}' count={c}")

        print("Janela aberta 15s...")
        page.wait_for_timeout(15000)
        browser.close()


if __name__ == "__main__":
    main()
