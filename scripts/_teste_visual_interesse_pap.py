"""
Teste visual: busca INTERESSE no Histórico PAP (sem relogar).

Objetivo: ver se o drawer precisa trocar Tipo=Venda → Interesse e o que a
SPA manda em /api/portal/vendas (tipoVenda=...).

Uso:
  $env:PAP_HEADLESS='false'
  python scripts/_teste_visual_interesse_pap.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
os.environ.setdefault("SECRET_KEY", "dev-test-visual-interesse")
os.environ["PYTHONIOENCODING"] = "utf-8"
# Visível por padrão neste script
os.environ.setdefault("PAP_HEADLESS", "false")

import django

django.setup()

from playwright.sync_api import sync_playwright

from crm_app.historico_pap import PAP_HISTORICO_URL, extrair_lista_api

SESSION = BASE / "pap_sessions" / "pap_session_TT833162.json"
SHOT_DIR = BASE / "scripts" / "_shots_interesse"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def _shot(page, name: str) -> None:
    path = SHOT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        print(f"[SHOT] {path}")
    except Exception as exc:
        print(f"[SHOT-FAIL] {name}: {exc}")


def _dump_drawer_tipo(page) -> dict:
    return page.evaluate(
        """() => {
            const root = document.querySelector('.MuiDrawer-paper, .MuiDrawer-root, .ant-drawer-open, [role="dialog"]')
                || document.body;
            const texts = [...root.querySelectorAll('label, span, p, div, li, button')]
                .map(el => (el.innerText || '').trim().replace(/\\s+/g, ' '))
                .filter(t => t && t.length < 80)
                .filter(t => /tipo|venda|interesse|pré|pre-?venda|select/i.test(t))
                .slice(0, 40);
            const selects = [...root.querySelectorAll('select, [role="combobox"], .MuiSelect-select, .ant-select-selector')]
                .map(el => ({
                    tag: el.tagName,
                    role: el.getAttribute('role') || '',
                    text: (el.innerText || el.textContent || '').trim().slice(0, 120),
                    aria: el.getAttribute('aria-label') || '',
                    id: el.id || '',
                    cls: (el.className || '').toString().slice(0, 80),
                }));
            const inputs = [...root.querySelectorAll('input')].slice(0, 30).map(i => ({
                type: i.type || '',
                value: i.value || '',
                ph: i.placeholder || '',
                name: i.name || '',
                id: i.id || '',
                aria: i.getAttribute('aria-label') || '',
            }));
            return { texts, selects, inputs, url: location.href };
        }"""
    )


def _abrir_filtros(page) -> bool:
    for sel in (
        "#drawer-filter",
        'button:has-text("Filtros")',
        'button:has-text("Filtrar")',
        '[aria-label*="Filtro" i]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    # fallback JS
    clicked = page.evaluate(
        """() => {
            const btns = [...document.querySelectorAll('button')];
            const b = btns.find(x => /filtro/i.test(x.innerText || '') || x.id === 'drawer-filter');
            if (!b) return false;
            b.click();
            return true;
        }"""
    )
    page.wait_for_timeout(800)
    return bool(clicked)


def _tentar_selecionar_interesse(page) -> dict:
    """Tenta abrir o select Tipo e escolher Interesse. Retorna diagnóstico."""
    diag = {"cliques": [], "ok": False, "apos": None}

    # 1) Clicar no campo que mostra "Venda" / Tipo
    for label in ("Venda", "Tipo", "Interesse"):
        try:
            loc = page.locator(
                f'.MuiDrawer-paper :text-is("{label}"), .MuiDrawer-paper :text("{label}")'
            ).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2000)
                diag["cliques"].append(f"text:{label}")
                page.wait_for_timeout(600)
                break
        except Exception as exc:
            diag["cliques"].append(f"fail text:{label}:{exc}")

    # 2) Opções do listbox / menu
    try:
        opts = page.evaluate(
            """() => [...document.querySelectorAll('[role="option"], .MuiMenuItem-root, .ant-select-item-option')]
                .map(el => (el.innerText || '').trim())
                .filter(Boolean)
                .slice(0, 30)"""
        )
        diag["opcoes"] = opts
        print("[TIPO] opções:", opts)
    except Exception as exc:
        diag["opcoes_err"] = str(exc)

    # 3) Clicar Interesse / INTERESSE_SALVO
    for nome in ("Interesse", "INTERESSE", "Interesse salvo", "INTERESSE_SALVO"):
        try:
            loc = page.locator(f'[role="option"]:has-text("{nome}"), .MuiMenuItem-root:has-text("{nome}")').first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2000)
                diag["cliques"].append(f"option:{nome}")
                diag["ok"] = True
                page.wait_for_timeout(500)
                break
        except Exception as exc:
            diag["cliques"].append(f"fail option:{nome}:{exc}")

    if not diag["ok"]:
        # JS: procura item de menu com Interesse
        ok = page.evaluate(
            """() => {
                const items = [...document.querySelectorAll('[role="option"], .MuiMenuItem-root, li')];
                const t = items.find(el => /interesse/i.test(el.innerText || ''));
                if (!t) return false;
                t.click();
                return true;
            }"""
        )
        diag["cliques"].append(f"js_interesse={ok}")
        diag["ok"] = bool(ok)

    diag["apos"] = _dump_drawer_tipo(page)
    return diag


def _aguardar_login_manual(page, *, timeout_s: int = 600) -> bool:
    """Não digita senha. Espera você logar (OTP/QR) na MESMA janela Chromium."""
    print(
        f"\n>>> Faça login na JANELA CHROMIUM DESTE TESTE (não em outro Chrome).\n"
        f">>> Aguardo até {timeout_s}s. Depois do login, deixe a janela aberta.\n"
    )
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            url = (page.url or "").lower()
        except Exception as exc:
            print(f"[WARN] página fechada? {exc}")
            return False

        no_login = "login.vtal" not in url and "nidp" not in url
        no_pap = "pap.niointernet.com.br" in url
        no_hist = "administrativo/historico" in url

        if no_hist:
            print("[OK] Já no Histórico.")
            return True

        if no_pap and no_login:
            print(f"[OK] Logado na SPA ({page.url[:100]}). Indo ao Histórico...")
            try:
                page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
            except Exception as exc:
                print(f"[WARN] goto histórico: {exc}")
            if "administrativo/historico" in (page.url or "").lower():
                return True
            if "login.vtal" not in (page.url or "").lower():
                # ainda na SPA — tenta menu / continua
                return True

        try:
            page.wait_for_timeout(1500)
        except Exception as exc:
            print(f"[WARN] browser fechou durante espera: {exc}")
            return False

        rest = int(timeout_s - (time.time() - t0))
        if rest % 20 < 2:
            print(f"... aguardando login ({rest}s) url={(page.url or '')[:90]}")
    return False


def main() -> int:
    aguardar = os.environ.get("PAP_AGUARDAR_LOGIN", "1").lower() not in ("0", "false", "no")
    if not SESSION.exists():
        print(f"STOP: sessão ausente ({SESSION}). Não vou logar.")
        return 2

    ini = date(2026, 9, 1)
    fim = date.today()
    headless = os.environ.get("PAP_HEADLESS", "false").lower() in ("1", "true", "yes")
    print("=== TESTE VISUAL INTERESSE ===")
    print(f"periodo {ini} -> {fim} | headless={headless} | aguardar_login={aguardar}")
    print(f"sessao {SESSION}")

    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=250 if not headless else 0)
        context = browser.new_context(
            storage_state=str(SESSION),
            viewport={"width": 1440, "height": 920},
        )
        page = context.new_page()

        def on_req(req):
            u = req.url or ""
            if "/api/portal/vendas" in u.lower():
                qs = parse_qs(urlparse(u).query)
                print("[NET→]", req.method, u[:220])
                print("       tipoVenda=", qs.get("tipoVenda") or qs.get("tipovenda"),
                      "status=", (qs.get("status") or [""])[0][:60])

        def on_route(route):
            req = route.request
            if req.method.upper() == "GET" and "/api/portal/vendas" in (req.url or "").lower():
                try:
                    resp = route.fetch()
                    body = None
                    try:
                        body = resp.json()
                    except Exception:
                        body = None
                    lista, total = extrair_lista_api(body) if body else ([], None)
                    captured.append({
                        "url": req.url,
                        "status": resp.status,
                        "itens": len(lista or []),
                        "total": total,
                    })
                    qs = parse_qs(urlparse(req.url).query)
                    print(
                        f"[CAP] HTTP {resp.status} itens={len(lista or [])} total={total} "
                        f"tipoVenda={qs.get('tipoVenda') or qs.get('tipovenda')}"
                    )
                    # amostra de tipoVenda nos itens
                    tipos = []
                    for it in (lista or [])[:8]:
                        if isinstance(it, dict):
                            tipos.append(it.get("tipoVenda") or it.get("tipo") or "?")
                    if tipos:
                        print(f"[CAP] amostra tipoVenda itens: {tipos}")
                    route.fulfill(response=resp)
                    return
                except Exception as exc:
                    print("[CAP-FAIL]", exc)
            route.continue_()

        page.on("request", on_req)
        page.route("**/api/portal/vendas**", on_route)

        page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        print("[PAGE]", page.url)
        if "login.vtal" in page.url.lower() or "nidp" in page.url.lower():
            _shot(page, "01_login_expirado")
            if not aguardar or headless:
                print("STOP: sessão expirou. NÃO vou logar.")
                browser.close()
                return 4
            if not _aguardar_login_manual(page):
                print("STOP: timeout aguardando login manual.")
                browser.close()
                return 4
            try:
                context.storage_state(path=str(SESSION))
                print(f"[OK] Sessão salva em {SESSION}")
            except Exception as exc:
                print(f"[WARN] não salvei sessão: {exc}")

        # Garante Histórico (pós-login às vezes cai em /geo ou callback)
        from crm_app.historico_pap_service import _navegar_ao_historico_spa

        for attempt in range(3):
            url_now = (page.url or "").lower()
            if "administrativo/historico" in url_now:
                break
            print(f"[NAV] tentativa {attempt+1}: indo ao Histórico (agora={page.url[:100]})")
            try:
                _navegar_ao_historico_spa(page, force_reload=True)
            except Exception:
                page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        print("[PAGE após nav]", page.url)
        if "administrativo/historico" not in (page.url or "").lower():
            print("STOP: não cheguei em /administrativo/historico")
            _shot(page, "02_fora_historico")
            browser.close()
            return 6

        _shot(page, "02_historico")

        print("\n--- Abrindo Filtros ---")
        if not _abrir_filtros(page):
            print("WARN: não abriu drawer de filtros")
        page.wait_for_timeout(1000)
        _shot(page, "03_drawer")
        dump = _dump_drawer_tipo(page)
        print("[DRAWER TIPO]", json.dumps(dump, ensure_ascii=False, indent=2)[:2500])

        print("\n--- Tentando selecionar Interesse (helper produção) ---")
        from crm_app.historico_pap_service import _selecionar_tipo_filtro_spa

        ok_tipo = _selecionar_tipo_filtro_spa(page, "INTERESSE")
        print("[SELECAO] ok=", ok_tipo)
        _shot(page, "04_apos_tipo")

        # Datas: reaproveita helpers de produção se possível
        print("\n--- Datas + Filtrar (helpers produção) ---")
        from crm_app.historico_pap_service import (
            _aguardar_filtrar_habilitado,
            _clicar_filtrar_no_drawer,
            _interagir_datas_mui_drawer,
            _scroll_drawer_ate_filtrar,
        )

        try:
            _interagir_datas_mui_drawer(page, ini, fim)
        except Exception as exc:
            print("[DATAS] erro:", exc)
        page.wait_for_timeout(500)
        _shot(page, "05_datas")
        try:
            _scroll_drawer_ate_filtrar(page)
            _aguardar_filtrar_habilitado(page)
            ok_f = _clicar_filtrar_no_drawer(page)
            print("[FILTRAR] clicked=", ok_f)
        except Exception as exc:
            print("[FILTRAR] erro:", exc)
        _shot(page, "06_apos_filtrar")

        # espera rede
        t0 = time.time()
        while time.time() - t0 < 20 and not captured:
            page.wait_for_timeout(400)

        print("\n=== RESUMO CAPTURAS ===")
        print(json.dumps(captured, ensure_ascii=False, indent=2))

        # Mantém aberto um pouco se visível
        if not headless:
            print("Janela aberta 8s para inspeção visual...")
            page.wait_for_timeout(8000)

        try:
            context.storage_state(path=str(SESSION))
        except Exception:
            pass
        browser.close()

    if not captured:
        print("RESULTADO: nenhuma /vendas capturada — provável clique/tipo errado.")
        return 3
    interesseish = [
        c for c in captured
        if any("INTERESSE" in str(x).upper() for x in (parse_qs(urlparse(c["url"]).query).get("tipoVenda") or []))
    ]
    if interesseish:
        print("RESULTADO: SPA chamou tipoVenda=INTERESSE* — UI ok.")
        return 0
    print(
        "RESULTADO: /vendas capturada, mas tipoVenda NÃO é INTERESSE "
        "(SPA ainda em Venda). Precisa clicar Tipo→Interesse e/ou reescrever URL."
    )
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
