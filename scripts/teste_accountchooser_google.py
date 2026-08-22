"""Testa se clicar no accountchooser recupera o acesso ao Forms."""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

FORM = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLScnXtSMB3EMutB88IfAg3ihGxUj60nAM6BZqmt4m24TsyPoAw/viewform"
)


def main() -> None:
    b64 = os.environ.get("GOOGLE_FORM_STORAGE_STATE_B64", "")
    email = os.environ.get("GOOGLE_FORM_EMAIL", "comunicacao@recordpap.com.br")
    assert b64, "Sem B64"
    state = ROOT / ".playwright_google_form_state.json"
    state.write_bytes(base64.b64decode(b64.strip()))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state))
        page = context.new_page()
        page.goto(FORM, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        print("URL1=", page.url[:140])

        if "accountchooser" in page.url:
            clicked = False
            for sel in [
                f'div[data-identifier="{email}"]',
                f'[data-email="{email}"]',
                f'text={email}',
                "li[data-identifier]",
                "div[data-identifier]",
            ]:
                loc = page.locator(sel)
                print("try", sel, "count", loc.count())
                if loc.count() > 0:
                    loc.first.click(timeout=5000)
                    clicked = True
                    break
            print("clicked=", clicked)
            page.wait_for_timeout(4000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

        # Se pedir senha, falha (não vamos automatizar aqui)
        print("URL2=", page.url[:140])
        if "docs.google.com/forms" in page.url and "accounts.google.com" not in page.url:
            n = page.locator('span:has-text("Enviar")').count()
            print("FORM_OK enviar=", n)
            context.storage_state(path=str(state))
            print("STATE_REFRESHED", state.stat().st_size)
        else:
            print("AINDA_LOGIN")
        browser.close()


if __name__ == "__main__":
    main()
