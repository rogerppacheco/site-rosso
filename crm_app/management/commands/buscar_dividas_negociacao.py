import base64
import hashlib
import json
from typing import Optional

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.core.management.base import BaseCommand

KEY_STRING = "TZkScM94x4Hvggpt"
PARAMS_URL = "https://negociacao.niointernet.com.br/negociar/params"
SITE_URL = "https://negociacao.niointernet.com.br/negociar"


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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/plain",
    }
    resp = session.get(PARAMS_URL, headers=headers, allow_redirects=True, timeout=20)
    if resp.status_code != 200:
        return None
    try:
        return decrypt_params(resp.text.strip())
    except Exception:
        return None


def fetch_params_playwright() -> tuple[Optional[dict], Optional[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright não instalado no venv"
    enc = None
    logs: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            nav_resp = page.goto(SITE_URL, wait_until="domcontentloaded")
            logs.append(f"goto status={getattr(nav_resp, 'status', lambda: None)() if nav_resp else None}")

            # força fetch direto pelo contexto para evitar bloqueio de JS
            resp = page.request.get(PARAMS_URL, headers={"Accept": "text/plain"})
            logs.append(f"request.get status={resp.status}")
            if resp.ok:
                enc = resp.text()
                logs.append(f"request.get len={len(enc)} ct={resp.headers.get('content-type')}")
            else:
                # fallback via fetch na página
                enc = page.evaluate(
                    "() => fetch('/negociar/params', {credentials:'include'}).then(r => r.text())"
                )
                logs.append(f"page.fetch len={len(enc) if enc else 0}")
            browser.close()
    except Exception as exc:  # pragma: no cover - logging apenas
        return None, f"Playwright falhou: {exc}"

    if not enc:
        log_str = " | ".join(logs)
        return None, f"Playwright não retornou conteúdo de /params; {log_str}"
    try:
        return decrypt_params(enc.strip()), None
    except Exception as exc:
        snippet = enc[:160].replace("\n", " ") if enc else ""
        log_str = " | ".join(logs)
        return None, f"Erro ao decriptar /params via Playwright: {exc}; len={len(enc) if enc else 0}; snippet='{snippet}'; {log_str}"


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


class Command(BaseCommand):
    help = "Busca dividas no site de negociacao da Nio via API interna"

    def add_arguments(self, parser):
        parser.add_argument("--cpf", required=True, help="CPF ou CNPJ sem formatacao")
        parser.add_argument("--offset", type=int, default=0, help="Offset da paginacao")
        parser.add_argument("--limit", type=int, default=10, help="Limite de itens")
        parser.add_argument("--no-playwright", action="store_true", help="Nao usar Playwright como fallback")

    def handle(self, *args, **options):
        cpf = options["cpf"]
        offset = options["offset"]
        limit = options["limit"]
        no_playwright = options["no_playwright"]

        session = requests.Session()

        params = fetch_params_requests(session)
        if not params and not no_playwright:
            params, pw_err = fetch_params_playwright()
        else:
            pw_err = None

        if not params:
            extra = f" Detalhe: {pw_err}" if pw_err else ""
            self.stdout.write(
                self.style.ERROR(
                    "Falha ao obter /params (token/apiServerUrl). Instale Playwright se necessario: python -m playwright install chromium" + extra
                )
            )
            return

        token = params.get("token")
        api_url = params.get("apiServerUrl")
        if not token or not api_url:
            self.stdout.write(self.style.ERROR("/params sem token ou apiServerUrl"))
            return

        session_id = get_session_id(api_url, token, session)
        if not session_id:
            self.stdout.write(self.style.ERROR("Falha ao obter sessionId"))
            return

        self.stdout.write(f"Token: {token[:20]}...")
        self.stdout.write(f"API base: {api_url}")
        self.stdout.write(f"Session-Id: {session_id}")

        try:
            data = get_debts(api_url, token, session_id, cpf, offset, limit, session)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Erro ao buscar dividas: {exc}"))
            return

        self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
