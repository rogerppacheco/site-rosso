import base64
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
b64 = os.environ["GOOGLE_FORM_STORAGE_STATE_B64"]
state = ROOT / ".tmp_state.json"
state.write_bytes(base64.b64decode(b64.strip()))
FORM = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLScnXtSMB3EMutB88IfAg3ihGxUj60nAM6BZqmt4m24TsyPoAw/viewform"
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(storage_state=str(state))
    page = context.new_page()
    page.goto(FORM, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    print("URL", page.url[:180])
    print("TITLE", page.title())
    body = (page.inner_text("body") or "")[:1000]
    print("BODY=", body.encode("ascii", "replace").decode("ascii").replace("\n", " | "))
    html = page.content()
    (ROOT / ".tmp_accountchooser.html").write_text(html, encoding="utf-8")
    print("HTML_LEN", len(html))
    low = html.lower()
    for needle in [
        "identifier",
        "account",
        "use another",
        "usar outra",
        "comunicacao",
        "continue",
        "challenge",
        "captcha",
        "rejected",
        "browser",
        "data-email",
        "data-identifier",
    ]:
        print(needle, low.count(needle))
    browser.close()
