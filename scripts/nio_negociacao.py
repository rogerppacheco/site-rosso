import argparse
import base64
import hashlib
import json
import os
import sys
from typing import Optional

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from crm_app.recaptcha_solver import RecaptchaSolver  # noqa: E402

KEY_STRING = "TZkScM94x4Hvggpt"
PARAMS_URL = "https://negociacao.niointernet.com.br/negociar/params"
SITE_URL = "https://negociacao.niointernet.com.br/negociar"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _try_solve_recaptcha(page, solver: RecaptchaSolver) -> None:
    """Tenta resolver reCAPTCHA v2 via solver externo e injeta o token na página."""
    try:
        site_key = page.evaluate("() => document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey') || null")
    except Exception:
        site_key = None
    if not site_key:
        return
    token = solver.solve_recaptcha_v2(site_key, SITE_URL)
    if not token:
        return
    try:
        page.evaluate(
            """
            (t) => {
                const selectors = [
                    'textarea[name="g-recaptcha-response"]',
                    '#g-recaptcha-response',
                    'input[name="g-recaptcha-response"]'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.value = t;
                        el.innerHTML = t;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                if (window.grecaptcha && window.grecaptcha.getResponse) {
                    try { window.grecaptcha.getResponse = () => t; } catch (e) {}
                }
            }
            """,
            token,
        )
        if os.getenv("NIO_DEBUG"):
            print("[debug] token de recaptcha injetado")
    except Exception as exc:
        if os.getenv("NIO_DEBUG"):
            print(f"[debug] falha ao injetar token de recaptcha: {exc}")


def decrypt_params(enc_b64: str) -> dict:
    data = base64.b64decode(enc_b64)
    if len(data) <= 16:
        raise ValueError("Encrypted payload too short")
    iv = data[:16]
    ct = data[16:]
    key = hashlib.sha256(KEY_STRING.encode()).digest()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    plain = cipher.decryptor().update(ct) + cipher.decryptor().finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(plain) + unpadder.finalize()
    return json.loads(plain)


def fetch_params_requests(session: requests.Session) -> Optional[dict]:
    headers = {
        "User-Agent": UA,
        "Accept": "text/plain",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = session.get(PARAMS_URL, headers=headers, allow_redirects=True, timeout=20)
    if os.getenv("NIO_DEBUG"):
        print(f"[debug] /params requests status={resp.status_code} len={len(resp.text)}")
    if resp.status_code != 200:
        return None
    try:
        return decrypt_params(resp.text.strip())
    except Exception as exc:
        if os.getenv("NIO_DEBUG"):
            snippet = resp.text[:200].replace("\n", " ")
            print(f"[debug] decrypt /params requests falhou: {exc}; body snippet: {snippet}")
        return None


def fetch_params_playwright(
    headless: bool = True,
    storage_state: Optional[str] = None,
    prompt_manual: bool = False,
    cpf: Optional[str] = None,
    solver: Optional[RecaptchaSolver] = None,
) -> Optional[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if os.getenv("NIO_DEBUG"):
            print("[debug] playwright não instalado (pip install playwright && python -m playwright install chromium)")
        return None

    enc = None
    try:
        with sync_playwright() as p:
            # Usa storage_state se existir para reutilizar cookies (ex: cf_clearance depois de resolver captcha manualmente).
            state_path = storage_state if storage_state and os.path.exists(storage_state) else None
            if os.getenv("NIO_DEBUG"):
                print(f"[debug] playwright headless={headless} storage_state_load={state_path}")

            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True,
                storage_state=state_path,
            )
            page = context.new_page()
            page.goto(SITE_URL, wait_until="networkidle", timeout=15000)
            if cpf:
                try:
                    page.fill("#inputId", cpf)
                    page.wait_for_timeout(300)
                except Exception as exc:
                    if os.getenv("NIO_DEBUG"):
                        print(f"[debug] falha ao preencher cpf: {exc}")
            # Se houver solver configurado, tenta resolver reCAPTCHA v2 antes de prosseguir
            if solver:
                _try_solve_recaptcha(page, solver)
            if prompt_manual:
                print("Abra a janela do navegador e resolva o desafio/captcha se aparecer; depois pressione Enter aqui para continuar...")
                try:
                    input()
                except EOFError:
                    pass
            page.wait_for_timeout(1500)
            # Tenta pegar token/apiServerUrl do localStorage (mais simples que /params).
            try:
                ls = page.evaluate("() => ({ token: localStorage.getItem('token'), apiServerUrl: localStorage.getItem('apiServerUrl') })")
                if ls and ls.get("token") and ls.get("apiServerUrl"):
                    if os.getenv("NIO_DEBUG"):
                        print("[debug] token/apiServerUrl lidos do localStorage")
                    enc = json.dumps(ls)
            except Exception as exc:
                if os.getenv("NIO_DEBUG"):
                    print(f"[debug] falha ao ler localStorage: {exc}")

            # Primeiro tenta via request API com headers que mimetizam XHR.
            try:
                resp = context.request.get(
                    PARAMS_URL,
                    headers={
                        "Accept": "text/plain, */*;q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                        "User-Agent": UA,
                        "Referer": SITE_URL,
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    },
                    timeout=15000,
                )
                if os.getenv("NIO_DEBUG"):
                    print(f"[debug] /params playwright request status={resp.status} len={len(resp.text())}")
                if resp.status == 200:
                    enc = resp.text()
            except Exception as exc:
                if os.getenv("NIO_DEBUG"):
                    print(f"[debug] playwright request.get exception: {exc}")

            # Fallback via fetch no contexto da página (carrega cookies). 
            if not enc:
                enc = page.evaluate(
                    "() => fetch('/negociar/params', {credentials:'include', headers:{'Accept':'text/plain, */*;q=0.01','X-Requested-With':'XMLHttpRequest','Accept-Language':'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'}}).then(r => r.text())"
                )
                if os.getenv("NIO_DEBUG"):
                    print(f"[debug] /params playwright fetch len={len(enc) if enc else 0}")
            if os.getenv("NIO_DEBUG") and enc:
                try:
                    dump_path = os.path.join(os.getcwd(), "params_debug.html")
                    with open(dump_path, "w", encoding="utf-8") as fh:
                        fh.write(enc)
                    print(f"[debug] corpo salvo em {dump_path}")
                except Exception as exc:
                    print(f"[debug] falha ao salvar dump: {exc}")
            if storage_state:
                try:
                    context.storage_state(path=storage_state)
                    if os.getenv("NIO_DEBUG"):
                        print(f"[debug] storage_state salvo em {storage_state}")
                except Exception as exc:
                    if os.getenv("NIO_DEBUG"):
                        print(f"[debug] falha ao salvar storage_state: {exc}")
            browser.close()
    except Exception as exc:
        if os.getenv("NIO_DEBUG"):
            print(f"[debug] playwright exception: {exc}")
        return None

    if enc is None:
        if os.getenv("NIO_DEBUG"):
            print("[debug] enc vazio: /params não retornou e localStorage não tinha token/apiServerUrl")
        return None
    try:
        # Se enc for um JSON com token/apiServerUrl (caso localStorage), retorna direto.
        parsed = json.loads(enc)
        if isinstance(parsed, dict) and parsed.get("token") and parsed.get("apiServerUrl"):
            return parsed
    except Exception:
        pass

    try:
        return decrypt_params(enc.strip())
    except Exception as exc:
        if os.getenv("NIO_DEBUG"):
            snippet = enc[:200].replace("\n", " ") if enc else ""
            print(f"[debug] decrypt /params playwright falhou: {exc}; body snippet: {snippet}")
        return None


def get_session_id(api_base: str, token: str, session: requests.Session) -> Optional[str]:
    url = api_base.rstrip("/") + "/authentication/sessionId"
    headers = {
        "Accept": "application/json",
        "Authorization": token,
    }
    resp = session.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("token")


def get_debts(api_base: str, token: str, session_id: str, cpf: str, offset: int, limit: int, session: requests.Session):
    url = api_base.rstrip("/") + f"/debts/customers/{cpf}?offset={offset}&limit={limit}&origin=nio"
    headers = {
        "Accept": "application/json",
        "Authorization": token,
        "Session-Id": session_id,
    }
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Consulta de dividas Nio via API interna")
    parser.add_argument("--cpf", required=True, help="CPF ou CNPJ sem formatacao")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--no-playwright", action="store_true", help="Nao usar Playwright como fallback para /params")
    parser.add_argument("--headful", action="store_true", help="Abrir navegador visivel para resolver captcha/manual se bloqueado")
    parser.add_argument("--storage-state", dest="storage_state", help="Arquivo JSON para salvar/reusar cookies (ex: cf_clearance)")
    parser.add_argument("--solve-captcha", action="store_true", help="Usar solver de captcha (CAPTCHA_API_KEY)")
    args = parser.parse_args()

    session = requests.Session()

    params = fetch_params_requests(session)
    if not params and not args.no_playwright:
        solver = RecaptchaSolver() if args.solve_captcha else None
        params = fetch_params_playwright(
            headless=not args.headful,
            storage_state=args.storage_state,
            prompt_manual=args.headful,
            cpf=args.cpf,
            solver=solver,
        )

    if not params:
        print("Falha ao obter /params (token/apiServerUrl). Tente com Playwright instalado: python -m playwright install chromium")
        sys.exit(1)

    token = params.get("token")
    api_url = params.get("apiServerUrl")
    if not token or not api_url:
        print("/params sem token ou apiServerUrl")
        sys.exit(1)

    session_id = get_session_id(api_url, token, session)
    if not session_id:
        print("Falha ao obter sessionId")
        sys.exit(1)

    print(f"Token: {token[:20]}...")
    print(f"API base: {api_url}")
    print(f"Session-Id: {session_id}")

    try:
        data = get_debts(api_url, token, session_id, args.cpf, args.offset, args.limit, session)
    except Exception as exc:
        print(f"Erro ao buscar dividas: {exc}")
        sys.exit(1)

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
