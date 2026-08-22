"""Diagnóstico rápido da sessão Google Forms no ambiente Railway."""
from __future__ import annotations

import base64
import json
import os
import sys
import time


def main() -> None:
    path = os.environ.get("GOOGLE_FORM_STORAGE_STATE", "")
    b64 = os.environ.get("GOOGLE_FORM_STORAGE_STATE_B64", "")
    print("PATH=", repr(path))
    print("B64_LEN=", len(b64 or ""))
    if not b64:
        print("SEM B64")
        sys.exit(1)
    raw = base64.b64decode(b64.strip())
    print("DECODED_BYTES=", len(raw), "START=", raw[:20])
    data = json.loads(raw)
    cookies = data.get("cookies") or []
    now = time.time()
    print("COOKIES=", len(cookies))
    for c in cookies:
        name = c.get("name") or ""
        if "SID" in name or name in ("HSID", "SSID", "APISID", "SAPISID", "LSID"):
            exp = c.get("expires") or -1
            left = round((exp - now) / 3600, 1) if isinstance(exp, (int, float)) and exp > 0 else "sess"
            print(f"  {name} domain={c.get('domain')} left_h={left}")

    # Teste Playwright: abre o form com a sessão
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("PLAYWRIGHT_IMPORT_FAIL", e)
        return

    form_url = (
        "https://docs.google.com/forms/d/e/"
        "1FAIpQLScnXtSMB3EMutB88IfAg3ihGxUj60nAM6BZqmt4m24TsyPoAw/viewform"
    )
    state_path = path or "/tmp/google_form_state.json"
    os.makedirs(os.path.dirname(state_path) or "/tmp", exist_ok=True)
    with open(state_path, "wb") as f:
        f.write(raw)
    print("WROTE", state_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()
        page.goto(form_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        url = page.url
        print("FINAL_URL=", url[:150])
        on_login = "accounts.google.com" in url
        on_form = "docs.google.com/forms" in url
        n_inputs = page.locator('input[type="text"]').count()
        n_enviar = page.locator('span:has-text("Enviar"), button:has-text("Enviar")').count()
        print("ON_LOGIN=", on_login, "ON_FORM=", on_form, "inputs=", n_inputs, "enviar=", n_enviar)
        browser.close()


if __name__ == "__main__":
    main()
