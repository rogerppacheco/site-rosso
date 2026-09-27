"""Busca PAP automatica limpa — SEM login. Periodo dia 1 do mes -> hoje."""
from __future__ import annotations

import os
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
os.environ.setdefault("SECRET_KEY", "dev-test-visual")
os.environ.setdefault("PAP_HEADLESS", "true")
os.environ["PYTHONIOENCODING"] = "utf-8"

import django

django.setup()

from playwright.sync_api import sync_playwright

from crm_app.historico_pap import PAP_HISTORICO_URL, extrair_lista_api
from crm_app.historico_pap_service import _coletar_vendas_via_rede_spa, _contar_itens_e_total_packs

SESSION = os.path.join(BASE, "pap_sessions", "pap_session_TT833162.json")


def main() -> int:
    if not os.path.exists(SESSION):
        print("STOP: sessao ausente — nao vou logar.")
        return 2

    hoje = date.today()
    ini = date(hoje.year, hoje.month, 1)
    print("=== BUSCA AUTOMATICA (limit=200 + paginas) ===")
    print(f"periodo {ini} -> {hoje}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.environ.get("PAP_HEADLESS", "true").lower() != "false")
        context = browser.new_context(
            storage_state=SESSION,
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        print("[PAGE]", page.url)
        if "login.vtal" in page.url.lower() or "nidp" in page.url.lower():
            print("STOP: sessao expirou. NAO vou logar.")
            browser.close()
            return 4

        packs = _coletar_vendas_via_rede_spa(
            page,
            data_inicio=ini,
            data_fim=hoje,
            timeout_ms=120000,
            max_paginas_ui=8,
        )
        n, tot = _contar_itens_e_total_packs(packs)
        for i, pack in enumerate(packs):
            lista, t = extrair_lista_api(pack.get("json"))
            url = (pack.get("url") or "")[:140]
            print(f"pack[{i}] status={pack.get('status')} itens={len(lista or [])} total_api={t}")
            print(f"  url={url}")

        print(f"=== RESULTADO pacotes={len(packs)} itens={n} total_api={tot} ===")
        try:
            context.storage_state(path=SESSION)
        except Exception:
            pass
        browser.close()
        if not packs:
            return 3
        if tot is not None and n < tot:
            print(f"WARN incomplete: {n}/{tot}")
            return 5
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
