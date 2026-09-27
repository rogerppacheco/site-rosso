"""Diagnóstico seguro do Histórico PAP — SEM login automático.

Objetivo: abrir o Chromium visível, você controla o login manualmente,
e validamos a coleta via REDE DA SPA (resposta de /vendas), sem forjar token.

Uso:
  python scripts/diagnostico_pap_historico_seguro.py --aguardar-login-manual --dias 30

  python scripts/diagnostico_pap_historico_seguro.py --usar-sessao-local --dias 30
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
os.environ.setdefault("SECRET_KEY", os.environ.get("SECRET_KEY", "dev-secret-key-diagnostico"))
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PAP_HEADLESS"] = "false"

import django

django.setup()

from playwright.sync_api import sync_playwright

from crm_app.historico_pap import PAP_HISTORICO_URL, extrair_lista_api
from crm_app.historico_pap_service import _coletar_vendas_via_rede_spa, limpar_jwt


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico seguro Histórico PAP (rede SPA)")
    parser.add_argument("--aguardar-login-manual", action="store_true")
    parser.add_argument("--usar-sessao-local", action="store_true")
    parser.add_argument("--matricula", default="")
    parser.add_argument("--dias", type=int, default=30)
    parser.add_argument(
        "--tambem-testar-http",
        action="store_true",
        help="Também tenta forjar Authorization (costuma dar jwt malformed)",
    )
    args = parser.parse_args()

    hoje = date.today()
    ini = hoje - timedelta(days=max(0, args.dias - 1))
    print("DIAGNÓSTICO SEGURO — nenhum login automático.")
    print(f"Período: {ini} → {hoje}")
    print("Estratégia principal: capturar JSON de /vendas gerado pela própria SPA.")

    sessions_dir = os.path.join(BASE_DIR, "pap_sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    session_file = None
    if args.matricula:
        candidato = os.path.join(sessions_dir, f"pap_session_{args.matricula.strip()}.json")
        if os.path.exists(candidato):
            session_file = candidato
    if not session_file:
        files = [
            os.path.join(sessions_dir, f)
            for f in os.listdir(sessions_dir)
            if f.startswith("pap_session_") and f.endswith(".json")
        ]
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        session_file = files[0] if files else None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=50,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        opts = {
            "viewport": {"width": 1366, "height": 768},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if args.usar_sessao_local and session_file:
            print(f"[INFO] Reusando sessão local: {session_file}")
            opts["storage_state"] = session_file
        elif args.usar_sessao_local:
            print("[AVISO] Nenhuma sessão local encontrada; abrindo limpo.")

        context = browser.new_context(**opts)
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")

        captured = {"auth": "", "eventos": 0}

        def _auth_parece_jwt(auth: str) -> bool:
            a = (auth or "").strip()
            if a.lower().startswith("bearer "):
                a = a[7:].strip()
            return a.startswith("eyJ") and a.count(".") >= 2 and len(a) >= 100

        def on_req(req):
            try:
                u = (req.url or "").lower()
                if "pap-api.niointernet.com.br" not in u:
                    return
                auth = req.headers.get("authorization") or req.headers.get("Authorization") or ""
                if not auth or len(auth) <= 20:
                    return
                captured["eventos"] += 1
                print(f"\n[CAPTURADO] {req.method} {req.url[:120]}")
                if _auth_parece_jwt(auth):
                    captured["auth"] = auth
                    print(f"[CAPTURADO] JWT len={len(auth)}")
            except Exception:
                pass

        page.on("request", on_req)

        if args.aguardar_login_manual:
            print("\n>>> Faça login MANUALMENTE no Chromium (QR/V.tal se pedir).")
            print(">>> Depois vá ao Histórico ou aguarde o script.")
            print(">>> NÃO feche o Chromium até o fim.")
            page.goto("https://pap.niointernet.com.br/", wait_until="domcontentloaded", timeout=60000)
            fim = time.time() + 600
            while time.time() < fim and not captured["auth"]:
                page.wait_for_timeout(500)
            if not captured["auth"]:
                print(f"[ERRO] Sem JWT (eventos={captured['eventos']}).")
                browser.close()
                return
        else:
            print("\n>>> Indo ao Histórico (sem login automático).")
            page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            if "login.vtal" in (page.url or "").lower() or "nidp" in (page.url or "").lower():
                print("[ERRO] Sessão local inválida (V.tal). Use --aguardar-login-manual.")
                browser.close()
                return
            for _ in range(60):
                if captured["auth"]:
                    break
                page.wait_for_timeout(500)

        print("\n=== COLETA VIA REDE DA SPA (/vendas) ===")
        packs = _coletar_vendas_via_rede_spa(
            page,
            data_inicio=ini,
            data_fim=hoje,
            timeout_ms=55000,
            max_paginas_ui=5,
        )
        total_itens = 0
        for i, pack in enumerate(packs, 1):
            lista, total = extrair_lista_api(pack.get("json"))
            n = len(lista or [])
            total_itens += n
            print(f"  pacote {i}: status={pack.get('status')} itens={n} total_api={total}")
            print(f"    url={(pack.get('url') or '')[:140]}")
        print(f"\n[RESULTADO] pacotes={len(packs)} itens_somados={total_itens}")
        if packs:
            print("[OK] Abordagem SPA funciona — produção deve usar captura de rede, não HTTP forjado.")
        else:
            print("[FALHA] SPA não disparou /vendas com sucesso. Confira se Filtrar abriu e se a tela tem dados.")

        if args.tambem_testar_http and captured["auth"]:
            from crm_app.historico_pap import STATUS_LISTA_PADRAO, montar_url_vendas
            from crm_app.historico_pap_service import _headers_auth

            url = montar_url_vendas(
                data_inicio=f"{ini.isoformat()}T00:00:00-03:00",
                data_fim=f"{hoje.isoformat()}T23:59:59-03:00",
                pdv="",
                tipo_api="VENDA",
                page=1,
                limit=15,
                status=STATUS_LISTA_PADRAO,
            )
            headers = _headers_auth(limpar_jwt(captured["auth"]), regenerar_anti_replay=True)
            print("\n=== CONTROLE (HTTP forjado — esperado 401) ===")
            try:
                resp = page.context.request.get(url, headers=headers, timeout=45000)
                print(f"context.request: {resp.status} {resp.text()[:180]}")
            except Exception as exc:
                print(f"context.request erro: {exc}")

        out = os.path.join(sessions_dir, "pap_session_diagnostico.json")
        try:
            context.storage_state(path=out)
            print(f"\n[OK] Sessão salva em {out}")
        except Exception as exc:
            print(f"[AVISO] Não salvou sessão: {exc}")

        print("\nNavegador aberto 45s (pode fechar se quiser; ignore erro se fechar).")
        try:
            page.wait_for_timeout(45000)
        except Exception as exc:
            print(f"[INFO] Browser fechado antes do timeout: {exc}")
        try:
            browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
