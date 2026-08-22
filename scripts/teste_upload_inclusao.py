"""Testa só o upload (com sessão salva), usando a função corrigida."""
from __future__ import annotations

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
    _fechar_picker_modal,
    _upload_arquivos_viabilidade,
)

FOTO = ROOT / "scripts" / "_teste_inclusao_foto.jpg"


def main() -> None:
    state = _caminho_storage_state()
    print("Foto:", FOTO)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=80)
        context = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        assert _esta_no_formulario(page), page.url
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

        ok = _upload_arquivos_viabilidade(page, [str(FOTO)])
        print("upload ok =", ok)
        if not ok:
            _fechar_picker_modal(page)
        page.wait_for_timeout(8000)
        browser.close()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
