"""
Grava sessão Google Forms (storage state) para a automação Inclusão.

Login = GOOGLE_FORM_LOGIN_EMAIL (ex.: roggerio@gmail.com) — conta que ABRE o form.
Campo do form = GOOGLE_FORM_EMAIL (ex.: comunicacao@...) — só preenchido no formulário.

Uso:
  .venv\\Scripts\\python.exe scripts\\salvar_sessao_google_form.py

Se o formulário já estiver aberto no Chrome e o script não detectar, pressione ENTER.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

os.environ["PAP_HEADLESS"] = "false"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decouple import config as env_config

for key in (
    "GOOGLE_FORM_EMAIL",
    "GOOGLE_FORM_LOGIN_EMAIL",
    "GOOGLE_FORM_PASSWORD",
    "GOOGLE_FORM_LOGIN_PASSWORD",
    "GOOGLE_FORM_STORAGE_STATE",
):
    val = env_config(key, default="")
    if val and key not in os.environ:
        os.environ[key] = str(val)

import django

django.setup()

from playwright.sync_api import sync_playwright

from crm_app.services_inclusao_viabilidade import (
    FORM_URL,
    _caminho_storage_state,
    _email_formulario,
    _email_login_google,
    _esta_no_formulario,
    _salvar_storage_state,
    _url_real_pagina,
)

TIMEOUT_LOGIN_SEGUNDOS = 10 * 60
POLL_SEGUNDOS = 2
PERFIL_DIR = ROOT / ".playwright_google_profile"


def _enter_pressionado() -> bool:
    """True se o usuário apertou ENTER no terminal (Windows/Unix)."""
    try:
        if os.name == "nt":
            import msvcrt

            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                return ch in ("\r", "\n")
            return False
        import select

        if select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            return True
    except Exception:
        pass
    return False


def _encontrar_pagina_formulario(context):
    """Percorre todas as abas e retorna a que tem o formulário aberto."""
    for pg in list(context.pages):
        try:
            if _esta_no_formulario(pg):
                return pg
        except Exception:
            continue
    return None


def main() -> None:
    state_path = _caminho_storage_state()
    email_login = _email_login_google()
    email_campo = _email_formulario()

    if PERFIL_DIR.exists():
        print(f"Limpando perfil antigo: {PERFIL_DIR}")
        shutil.rmtree(PERFIL_DIR, ignore_errors=True)
    PERFIL_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("GRAVAR SESSÃO GOOGLE FORMS (Inclusão)")
    print(f"Login (sessão):     {email_login}")
    print(f"Campo do formulário: {email_campo}")
    print(f"Storage state: {state_path}")
    print("=" * 60)
    print()
    print("1) O Chrome vai abrir (perfil limpo).")
    print(f"2) Faça login com: {email_login}")
    print(f"3) O e-mail {email_campo} NÃO precisa logar — só entra no campo do form.")
    print("4) Pule passkey / 'Agora não' se aparecer.")
    print("5) Quando o formulário abrir, o script salva sozinho.")
    print("6) Se o form já estiver aberto e o script não detectar: pressione ENTER aqui.")
    print()

    with sync_playwright() as p:
        launch_kwargs = {
            "user_data_dir": str(PERFIL_DIR),
            "headless": False,
            "viewport": {"width": 1280, "height": 900},
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"],
        }
        try:
            context = p.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
            print("Usando: Google Chrome (channel=chrome)")
        except Exception as e:
            print(f"Chrome não disponível ({e}); usando Chromium Playwright.")
            context = p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        print(f"URL inicial: {_url_real_pagina(page)}")
        print("Aguardando formulário... (ENTER força o salvamento)")
        print()

        deadline = time.time() + TIMEOUT_LOGIN_SEGUNDOS
        form_ok = False
        forcar = False
        while time.time() < deadline:
            if _enter_pressionado():
                print("ENTER detectado — salvando sessão da janela atual...")
                forcar = True
                # Preferir aba com form; senão a última
                page = _encontrar_pagina_formulario(context) or context.pages[-1]
                form_ok = True
                break

            page_form = _encontrar_pagina_formulario(context)
            if page_form is not None:
                page = page_form
                form_ok = True
                break

            restante = int(deadline - time.time())
            urls = []
            for i, pg in enumerate(list(context.pages)):
                try:
                    urls.append(f"aba{i}={_url_real_pagina(pg)[:70]}")
                except Exception:
                    urls.append(f"aba{i}=?")
            print(f"  [{restante:3d}s] {' | '.join(urls) or '?'}", flush=True)
            time.sleep(POLL_SEGUNDOS)

        if not form_ok:
            print()
            print("TIMEOUT — formulário não detectado.")
            for i, pg in enumerate(list(context.pages)):
                try:
                    print(f"  aba{i}: {_url_real_pagina(pg)}")
                except Exception:
                    pass
            context.close()
            print(f"Nada foi salvo. Faça login com {email_login} e tente de novo.")
            sys.exit(1)

        if not forcar and "accountchooser" in (_url_real_pagina(page) or ""):
            print("Ainda no accountchooser — selecione", email_login)
            context.close()
            sys.exit(1)

        # Se forçou ENTER ainda no login, tenta ir ao form com cookies atuais
        if forcar and not _esta_no_formulario(page):
            print("Abrindo formulário com a sessão atual...")
            try:
                page.goto(FORM_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
            except Exception as e:
                print("Falha ao abrir form:", e)

        print()
        print(f"Formulário detectado! URL: {_url_real_pagina(page)[:120]}")
        if not _esta_no_formulario(page) and not forcar:
            print("AVISO: página pode não ser o form; salvando assim mesmo sob pedido.")
        page.wait_for_timeout(1000)
        salvo = _salvar_storage_state(context)
        context.close()

        if salvo and os.path.isfile(salvo):
            print()
            print(f"OK — sessão salva ({os.path.getsize(salvo)} bytes):")
            print(f"  {salvo}")
            print()
            print("Próximo passo (produção):")
            print("  .\\.venv\\Scripts\\python.exe scripts\\publicar_sessao_google_railway.py")
        else:
            print("Falha ao salvar storage state.")
            sys.exit(1)


if __name__ == "__main__":
    main()
