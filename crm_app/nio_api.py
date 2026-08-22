import base64
import hashlib
import json
import logging
import os
import threading
import time
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings

from .recaptcha_solver import RecaptchaSolver

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
PARAMS_URL = "https://negociacao.niointernet.com.br/negociar/params"
SITE_URL = "https://negociacao.niointernet.com.br/negociar"
KEY_STRING = "TZkScM94x4Hvggpt"
DEFAULT_STORAGE_STATE = getattr(settings, "NIO_STORAGE_STATE", os.path.join(settings.BASE_DIR, ".playwright_state.json"))

# =============================================================================
# CACHE DE TOKEN + LOCK PARA EVITAR MÚLTIPLOS PLAYWRIGHTS
# =============================================================================
# Este cache evita que múltiplas requisições simultâneas abram várias
# instâncias do Playwright ao mesmo tempo, o que causava travamento do servidor.

_token_cache = {
    "params": None,           # Dados do token (token, apiServerUrl)
    "timestamp": 0,           # Quando foi obtido
    "expires_in": 1800,       # Validade em segundos (30 minutos)
}
_token_lock = threading.Lock()  # Lock para garantir apenas 1 Playwright por vez


def get_cached_params(headless: bool = True, storage_state: Optional[str] = None, force_refresh: bool = False) -> Optional[dict]:
    """
    Obtém os parâmetros (token/apiServerUrl) usando cache inteligente.
    
    - Se o cache estiver válido, retorna imediatamente (sem Playwright)
    - Se o cache expirou, apenas UMA thread busca novo token (outras aguardam)
    - Isso evita múltiplos Playwrights rodando simultaneamente
    
    Args:
        headless: Se True, roda Playwright em modo headless
        storage_state: Caminho para arquivo de estado do Playwright
        force_refresh: Se True, ignora cache e busca novo token
    
    Returns:
        dict com token e apiServerUrl, ou None se falhar
    """
    global _token_cache
    
    current_time = time.time()
    
    # 1. Verificar se cache está válido (sem lock - leitura rápida)
    if not force_refresh:
        cache_age = current_time - _token_cache["timestamp"]
        if _token_cache["params"] and cache_age < _token_cache["expires_in"]:
            logger.info(f"[NIO CACHE] ✅ Usando token do cache (idade: {cache_age:.0f}s)")
            return _token_cache["params"]
    
    # 2. Cache expirado ou vazio - precisamos buscar novo token
    # Usar lock para garantir que apenas uma thread busca
    with _token_lock:
        # Re-verificar cache dentro do lock (outra thread pode ter atualizado)
        current_time = time.time()
        cache_age = current_time - _token_cache["timestamp"]
        if not force_refresh and _token_cache["params"] and cache_age < _token_cache["expires_in"]:
            logger.info(f"[NIO CACHE] ✅ Token atualizado por outra thread (idade: {cache_age:.0f}s)")
            return _token_cache["params"]
        
        logger.info("[NIO CACHE] 🔄 Cache expirado/vazio. Buscando novo token...")
        
        # 3. Tentar via requests primeiro (mais rápido, sem Playwright)
        session = requests.Session()
        params = fetch_params_requests(session)
        
        if params:
            logger.info("[NIO CACHE] ✅ Token obtido via requests (sem Playwright)")
        else:
            # 4. Fallback: Playwright em thread dedicada. A API sync deixa um
            # event loop na OS thread; se rodar na thread do Gunicorn, o JWT/ORM
            # dos próximos requests falha com SynchronousOnlyOperation.
            logger.info("[NIO CACHE] ⚠️ Requests falhou. Usando Playwright (apenas 1 instância)...")
            params = _fetch_params_playwright_isolado(
                headless=headless, storage_state=storage_state
            )
            
            if params:
                logger.info("[NIO CACHE] ✅ Token obtido via Playwright")
            else:
                logger.error("[NIO CACHE] ❌ Falha ao obter token (requests e Playwright falharam)")
                return None
        
        # 5. Atualizar cache
        _token_cache["params"] = params
        _token_cache["timestamp"] = time.time()
        logger.info(f"[NIO CACHE] 💾 Token salvo no cache (válido por {_token_cache['expires_in']}s)")
        
        return params


def invalidate_token_cache():
    """Invalida o cache de token (útil quando token expira no meio de uma operação)"""
    global _token_cache
    with _token_lock:
        _token_cache["params"] = None
        _token_cache["timestamp"] = 0
        logger.info("[NIO CACHE] 🗑️ Cache invalidado")


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
    if resp.status_code != 200:
        return None
    try:
        return decrypt_params(resp.text.strip())
    except Exception:
        return None


def _try_solve_recaptcha_nio(page, solver: RecaptchaSolver) -> None:
    """Tenta resolver reCAPTCHA v2 via solver e injeta o token."""
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
    except Exception:
        pass


def _fetch_params_playwright_isolado(
    headless: bool = True, storage_state: Optional[str] = None, timeout_seconds: int = 120
) -> Optional[dict]:
    """Roda Playwright fora da thread HTTP para não envenenar o Gunicorn."""
    resultado: list[Optional[dict]] = [None]
    erro: list[Optional[BaseException]] = [None]

    def alvo() -> None:
        try:
            resultado[0] = fetch_params_playwright(
                headless=headless, storage_state=storage_state
            )
        except BaseException as exc:  # noqa: BLE001 - repassado à chamadora
            erro[0] = exc

    thread = threading.Thread(target=alvo, name="nio-token-playwright", daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if erro[0] is not None:
        raise erro[0]
    if thread.is_alive():
        logger.error("[NIO CACHE] Playwright de token expirou após %ss", timeout_seconds)
        return None
    return resultado[0]


def fetch_params_playwright(headless: bool = True, storage_state: Optional[str] = None) -> Optional[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    enc = None
    state_path = storage_state if storage_state else DEFAULT_STORAGE_STATE
    load_state = state_path if state_path and os.path.exists(state_path) else None
    
    # Inicializa solver se API key estiver disponível
    captcha_api_key = getattr(settings, "CAPTCHA_API_KEY", None) or os.getenv("CAPTCHA_API_KEY")
    solver = RecaptchaSolver(api_key=captcha_api_key) if captcha_api_key else None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True,
                storage_state=load_state,
            )
            page = context.new_page()
            page.goto(SITE_URL, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1200)
            
            # Tenta resolver reCAPTCHA se solver estiver disponível
            if solver:
                _try_solve_recaptcha_nio(page, solver)
                page.wait_for_timeout(500)

            # Primeiro: tenta ler token/apiServerUrl já persistidos no localStorage.
            try:
                ls = page.evaluate(
                    "() => ({ token: localStorage.getItem('token'), apiServerUrl: localStorage.getItem('apiServerUrl') })"
                )
                if ls and ls.get("token") and ls.get("apiServerUrl"):
                    enc = json.dumps(ls)
            except Exception:
                pass

            # Segundo: tenta via request API com headers de XHR.
            if not enc:
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
                    if resp.status == 200:
                        enc = resp.text()
                except Exception:
                    pass

            # Terceiro: fetch dentro da página com cookies carregados.
            if not enc:
                try:
                    enc = page.evaluate(
                        "() => fetch('/negociar/params', {credentials:'include', headers:{'Accept':'text/plain, */*;q=0.01','X-Requested-With':'XMLHttpRequest','Accept-Language':'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'}}).then(r => r.text())"
                    )
                except Exception:
                    pass

            # Persiste storage state para reaproveitar cookies.
            if state_path:
                try:
                    os.makedirs(os.path.dirname(state_path), exist_ok=True) if os.path.dirname(state_path) else None
                    context.storage_state(path=state_path)
                except Exception:
                    pass

            browser.close()
    except Exception:
        return None

    if enc is None:
        return None

    # Se enc for JSON simples com token/apiServerUrl, retorna direto.
    try:
        parsed = json.loads(enc)
        if isinstance(parsed, dict) and parsed.get("token") and parsed.get("apiServerUrl"):
            return parsed
    except Exception:
        pass

    try:
        return decrypt_params(enc.strip())
    except Exception:
        return None


def get_session_id(api_base: str, token: str, session: requests.Session) -> Optional[str]:
    url = api_base.rstrip("/") + "/authentication/sessionId"
    headers = {"Accept": "application/json", "Authorization": token}
    resp = session.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("token")


def get_debts(api_base: str, token: str, session_id: str, cpf: str, offset: int, limit: int, session: requests.Session):
    import logging
    logger = logging.getLogger(__name__)
    
    # Garantir que CPF contém apenas números
    cpf_limpo = ''.join(filter(str.isdigit, str(cpf)))
    if not cpf_limpo or len(cpf_limpo) < 11:
        logger.error(f"[M10] CPF inválido após limpeza: {cpf} -> {cpf_limpo}")
        raise ValueError(f"CPF inválido: {cpf}")
    
    url = api_base.rstrip("/") + f"/debts/customers/{cpf_limpo}?offset={offset}&limit={limit}&origin=nio"
    headers = {
        "Accept": "application/json",
        "Authorization": token,
        "Session-Id": session_id,
    }
    
    logger.debug(f"[M10] Requisição GET: {url}")
    logger.debug(f"[M10] Headers: Authorization={token[:20]}..., Session-Id={session_id[:20]}...")
    
    resp = session.get(url, headers=headers, timeout=30)
    
    if resp.status_code == 400:
        logger.warning(f"[M10] API Nio 400 para CPF (não encontrado ou inválido): {url}")
        try:
            body = resp.json()
            detail = body.get("message") or body.get("detail") or body.get("error") or str(body)[:200]
        except Exception:
            detail = resp.text[:200] if resp.text else "Bad Request"
        if isinstance(detail, dict):
            detail = str(detail)[:200]
        return {"debts": [], "erro_400": True, "detail": detail}
    
    if resp.status_code != 200:
        logger.error(f"[M10] Erro {resp.status_code} na requisição: {url}")
        logger.error(f"[M10] Response headers: {dict(resp.headers)}")
        try:
            logger.error(f"[M10] Response body: {resp.text[:500]}")
        except Exception:
            pass
        resp.raise_for_status()
    
    return resp.json()


def get_invoice_pdf_url(api_base: str, token: str, session_id: str, debt_id: str, invoice_id: str, cpf: str, reference_month: str, session: requests.Session) -> Optional[str]:
    """
    Tenta obter a URL do PDF da fatura através da API Nio ou construindo URL S3.
    
    Args:
        api_base: Base URL da API
        token: Token de autorização
        session_id: ID da sessão
        debt_id: ID da dívida
        invoice_id: ID da invoice
        cpf: CPF do cliente (sem formatação)
        reference_month: Mês de referência (YYYYMM)
        session: Sessão HTTP
    
    Returns:
        URL do PDF ou None
    """
    # Padrão da URL S3 que observamos:
    # https://cobranca-nio-6490.s3.sa-east-1.amazonaws.com/modal_{cpf}_{YYYYMM}_{random}.pdf?[assinatura]
    
    try:
        # Tenta vários endpoints possíveis
        endpoints = [
            f"/debts/{debt_id}/invoices/{invoice_id}/download",
            f"/debts/{debt_id}/invoices/{invoice_id}/pdf",
            f"/invoices/{invoice_id}/download",
            f"/invoices/{invoice_id}/pdf",
        ]
        
        headers = {
            "Accept": "application/pdf,application/json,*/*",
            "Authorization": token,
            "Session-Id": session_id,
        }
        
        for endpoint in endpoints:
            url = api_base.rstrip("/") + endpoint
            try:
                logger.debug("[PDF API] Tentando: %s", url)
                resp = session.get(url, headers=headers, timeout=10, allow_redirects=True)
                logger.debug("[PDF API] Status: %s, Content-Type: %s", resp.status_code, resp.headers.get("content-type", "N/A"))

                # Se retornou JSON com URL do PDF
                if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                    data = resp.json()
                    logger.debug("[PDF API] JSON response: %s", data)
                    if data.get("url") or data.get("pdf_url") or data.get("download_url"):
                        pdf_url = data.get("url") or data.get("pdf_url") or data.get("download_url")
                        logger.info("[PDF API] URL obtida via JSON: %s...", (pdf_url or "")[:80])
                        return pdf_url

                # Se retornou redirect para S3
                elif resp.status_code in (200, 302, 301):
                    logger.debug("[PDF API] Final URL: %s", resp.url)
                    if "s3" in resp.url and ".pdf" in resp.url:
                        logger.info("[PDF API] URL obtida via redirect: %s...", resp.url[:80])
                        return resp.url

                if len(resp.text) < 500:
                    logger.debug("[PDF API] Response: %s", resp.text[:200])

            except Exception as e:
                logger.debug("[PDF API] Erro no endpoint %s: %s", endpoint, e)
                continue

        logger.debug("[PDF API] Nenhum endpoint retornou PDF válido")
        return None

    except Exception as e:
        logger.debug("[PDF API] Erro ao buscar URL do PDF: %s", e)
        return None


def _map_invoice(invoice: Dict, debt: Dict) -> Dict:
    return {
        "debt_id": debt.get("debtId"),
        "invoice_id": invoice.get("id"),  # ID da invoice para buscar PDF
        "deal_code": debt.get("dealCode"),
        "product": debt.get("productName"),
        "origin": debt.get("origin"),
        "amount": invoice.get("amount"),
        "reference_month": invoice.get("referenceMonth"),
        "due_date_raw": invoice.get("dueDate"),
        "expiration": invoice.get("expirationDate"),
        "status": invoice.get("status") or debt.get("status"),
        "barcode": invoice.get("barCode"),
        "pix": invoice.get("originalPixCode") or invoice.get("pixCode"),
        "cpf_cnpj": invoice.get("cpfCnpj"),
    }


def consultar_dividas_nio(cpf: str, offset: int = 0, limit: int = 10, storage_state: Optional[str] = None, headless: bool = True) -> Dict:
    """
    Consulta dívidas no Nio usando cache de token para evitar múltiplos Playwrights.
    
    O cache garante que:
    - Se o token estiver válido, usa direto (sem abrir Playwright)
    - Se precisar renovar, apenas UMA instância do Playwright é aberta
    - Outras requisições aguardam e usam o token renovado
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[M10] Iniciando consulta NIO para CPF: {cpf}")
    session = requests.Session()

    try:
        # USAR CACHE DE TOKEN - evita múltiplos Playwrights simultâneos
        params = get_cached_params(headless=headless, storage_state=storage_state)
        
        if not params:
            logger.error("[M10] Falha ao obter token/apiServerUrl (possível bloqueio/captcha). Rode headful para renovar cookies.")
            raise RuntimeError("Falha ao obter token/apiServerUrl (possível bloqueio/captcha). Rode headful para renovar cookies.")

        token = params.get("token")
        api_url = params.get("apiServerUrl")
        logger.info(f"[M10] Token: {token}, API URL: {api_url}")
        if not token or not api_url:
            logger.error("[M10] /params sem token ou apiServerUrl")
            raise RuntimeError("/params sem token ou apiServerUrl")

        session_id = get_session_id(api_url, token, session)
        logger.info(f"[M10] Session ID: {session_id}")
        if not session_id:
            logger.error("[M10] Falha ao obter sessionId")
            raise RuntimeError("Falha ao obter sessionId")

        data = get_debts(api_url, token, session_id, cpf, offset, limit, session)
        logger.info(f"[M10] Dados recebidos: {data}")
        if data.get("erro_400"):
            return {
                "token": None,
                "api_base": api_url,
                "session_id": None,
                "invoices": [],
                "raw": data,
                "erro_400": True,
                "detail": data.get("detail", "CPF não encontrado ou inválido na base Nio"),
            }
        invoices = []
        for debt in data.get("debts", []):
            for inv in debt.get("invoices", []) or []:
                invoices.append(_map_invoice(inv, debt))
        logger.info(f"[M10] Faturas mapeadas: {len(invoices)}")
        return {
            "token": token,
            "api_base": api_url,
            "session_id": session_id,
            "invoices": invoices,
            "raw": data,
        }
    except Exception as e:
        logger.exception(f"[M10] Erro na consulta NIO: {e}")
        raise
