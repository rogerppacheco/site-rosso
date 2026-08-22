# crm_app/services_inclusao_viabilidade.py
"""
Serviço para automação de solicitação de viabilidade (Inclusão) via Google Forms.
- Consulta ViaCEP para endereço
- Nominatim para coordenadas
- Street View Static API para foto automática
- Playwright para preencher o formulário
"""
import logging
import os
import re
import tempfile
from typing import Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None

# Constantes
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScnXtSMB3EMutB88IfAg3ihGxUj60nAM6BZqmt4m24TsyPoAw/viewform"

# Valores fixos do formulário
CODIGO_SAP = "1068561"
EXECUTIVO = "ROGERIO PEREIRA PACHECO"
TIPO_CANAL = "PAP"
EMPRESA_VENDAS = "RECORD"

# Mapeamento UF (sigla ViaCEP) -> nome completo (Google Forms)
UF_SIGLA_PARA_NOME = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santos", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}

# Mapeamento tipo logradouro (primeira palavra) -> opção do formulário
TIPO_LOGRADOURO_MAP = {
    "ALAMEDA": "Alameda",
    "AVENIDA": "Avenida",
    "AV": "Avenida",
    "BECO": "Beco",
    "TRAVESSA": "Travessa",
    "TRAV": "Travessa",
    "RUA": "Rua",
    "RODOVIA": "Rodovia",
    "BR": "Rodovia",
    "SERVIDAO": "Servidão",
    "SERVIDÃO": "Servidão",
}


def _env_ou_decouple(chave: str, default: str = "") -> str:
    """Lê variável de ambiente; se vazia, tenta django-environ/decouple (.env)."""
    val = (os.environ.get(chave) or "").strip()
    if val:
        return val
    try:
        from decouple import config as env_config
        return str(env_config(chave, default=default) or default).strip()
    except Exception:
        return default


def _email_formulario() -> str:
    """E-mail preenchido no *campo* do Google Forms (não é a conta de login)."""
    return _env_ou_decouple("GOOGLE_FORM_EMAIL", "comunicacao@recordpap.com.br")


def _email_login_google() -> str:
    """
    Conta Google usada para autenticar / abrir o formulário (storage state).
    Separada do e-mail do campo do form.
    """
    return _env_ou_decouple(
        "GOOGLE_FORM_LOGIN_EMAIL",
        "roggerio@gmail.com",
    )


def _senha_login_google() -> str:
    """Senha da conta de login. Aceita GOOGLE_FORM_LOGIN_PASSWORD ou fallback GOOGLE_FORM_PASSWORD."""
    return _env_ou_decouple("GOOGLE_FORM_LOGIN_PASSWORD", "") or _env_ou_decouple(
        "GOOGLE_FORM_PASSWORD", ""
    )


def _senha_formulario() -> str:
    """Compat: senha de login (legado usava GOOGLE_FORM_PASSWORD)."""
    return _senha_login_google()


def _caminho_storage_state() -> str:
    """Caminho do storage state Playwright da sessão Google Forms."""
    path = getattr(settings, "GOOGLE_FORM_STORAGE_STATE", None)
    if path:
        return str(path)
    return os.path.join(str(settings.BASE_DIR), ".playwright_google_form_state.json")


def _garantir_storage_state_arquivo() -> bool:
    """
    Garante que o arquivo de sessão exista.
    Em produção (Railway) o disco do container é efêmero — use
    GOOGLE_FORM_STORAGE_STATE_B64 com o JSON em base64 (gerado localmente
    por scripts/salvar_sessao_google_form.py).
    """
    path = _caminho_storage_state()
    if os.path.isfile(path) and os.path.getsize(path) > 50:
        return True

    b64 = _env_ou_decouple("GOOGLE_FORM_STORAGE_STATE_B64", "")
    if not b64:
        return False

    try:
        import base64

        raw = base64.b64decode(b64.strip(), validate=False)
        # Aceitar JSON puro ou já em bytes
        if raw[:1] != b"{":
            # às vezes cola-se o JSON sem base64 por engano
            raw = b64.strip().encode("utf-8")
        pasta = os.path.dirname(path)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        logger.info(
            "[Inclusão] Storage state escrito a partir de GOOGLE_FORM_STORAGE_STATE_B64 (%s bytes) -> %s",
            len(raw),
            path,
        )
        return True
    except Exception as e:
        logger.warning("[Inclusão] Falha ao materializar storage state do env: %s", e)
        return False


def _url_real_pagina(page) -> str:
    """URL efetiva da página (location.href), mais confiável que page.url após login Google."""
    try:
        href = page.evaluate("() => location.href")
        if href:
            return str(href)
    except Exception:
        pass
    try:
        return page.url or ""
    except Exception:
        return ""


def _esta_no_formulario(page) -> bool:
    """True se a página atual parece ser o Google Forms (não a tela de login)."""
    try:
        url = (_url_real_pagina(page) or "").lower()
    except Exception:
        return False

    # Conteúdo do form (mais confiável que a URL sozinha)
    try:
        if page.locator('div[role="listbox"]').count() >= 1:
            return True
        if page.locator('span:has-text("Enviar"), button:has-text("Enviar")').count() > 0:
            return True
        if page.get_by_text("Limpar formulário", exact=False).count() > 0:
            return True
    except Exception:
        pass

    if "accounts.google.com" in url:
        return False
    if "docs.google.com/forms" in url:
        return True
    return False


def _salvar_storage_state(context) -> Optional[str]:
    """Persiste cookies/sessão Google para reuso. Retorna o caminho ou None."""
    path = _caminho_storage_state()
    try:
        pasta = os.path.dirname(path)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        context.storage_state(path=path)
        logger.info("[Inclusão] Storage state Google salvo em %s", path)
        return path
    except Exception as e:
        logger.warning("[Inclusão] Falha ao salvar storage state: %s", e)
        return None


def _invalidar_storage_state() -> None:
    """Remove sessão salva (ex.: expirada / login inválido)."""
    path = _caminho_storage_state()
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.info("[Inclusão] Storage state invalidado: %s", path)
    except Exception as e:
        logger.warning("[Inclusão] Não foi possível invalidar storage state: %s", e)


def _limpar_cep(cep: str) -> str:
    """Retorna apenas dígitos do CEP."""
    return re.sub(r'\D', '', str(cep or ''))[:8]


def consultar_viacep(cep: str) -> Optional[dict]:
    """
    Consulta ViaCEP e retorna dados do endereço.
    Retorna None se CEP inválido.
    """
    cep_limpo = _limpar_cep(cep)
    if len(cep_limpo) != 8:
        return None
    try:
        resp = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get('erro'):
            return None
        return {
            'cep': data.get('cep', cep_limpo),
            'logradouro': data.get('logradouro') or '',
            'bairro': data.get('bairro') or '',
            'localidade': data.get('localidade') or '',
            'uf': data.get('uf') or '',
        }
    except Exception as e:
        logger.warning(f"[Inclusão] ViaCEP erro: {e}")
        return None


def obter_tipo_logradouro(logradouro: str) -> str:
    """
    Extrai o tipo de logradouro da primeira palavra.
    Retorna 'Outros' se não encontrar mapeamento.
    """
    if not logradouro or not isinstance(logradouro, str):
        return "Outros"
    partes = logradouro.strip().upper().split()
    if not partes:
        return "Outros"
    primeira = partes[0].replace(".", "")
    return TIPO_LOGRADOURO_MAP.get(primeira, "Outros")


def buscar_coordenadas(endereco_completo: str) -> Optional[dict]:
    """
    Busca coordenadas (lat, lng) via Nominatim.
    endereco_completo: ex "Rua X, 123, Cidade - UF, Brasil"
    """
    try:
        headers = {'User-Agent': 'RecordPAP_Inclusao/1.0'}
        params = {'q': endereco_completo, 'format': 'json', 'limit': 1}
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=headers,
            timeout=5
        )
        if resp.status_code == 200 and resp.json():
            r = resp.json()[0]
            return {
                'lat': float(r['lat']),
                'lng': float(r['lon']),
                'lat_str': r['lat'],
                'lng_str': r['lon'],
            }
    except Exception as e:
        logger.warning(f"[Inclusão] Nominatim erro: {e}")
    return None


def baixar_street_view(lat: float, lng: float, tamanho: str = "640x640") -> Optional[str]:
    """
    Baixa imagem do Street View Static API.
    Retorna o caminho do arquivo salvo ou None se falhar.
    """
    api_key = os.environ.get('GOOGLE_STREETVIEW_API_KEY') or getattr(
        settings, 'GOOGLE_STREETVIEW_API_KEY', None
    )
    if not api_key:
        logger.warning("[Inclusão] GOOGLE_STREETVIEW_API_KEY não configurada")
        return None
    try:
        location = f"{lat},{lng}"
        url = (
            "https://maps.googleapis.com/maps/api/streetview"
            f"?size={tamanho}&location={location}&key={api_key}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[Inclusão] Street View API status {resp.status_code}")
            return None
        # Verificar se retornou imagem válida (API retorna imagem ou HTML de erro)
        ct = resp.headers.get('Content-Type', '')
        if 'image' not in ct:
            logger.warning(f"[Inclusão] Street View não retornou imagem: {ct}")
            return None
        fd, path = tempfile.mkstemp(suffix='.jpg', prefix='streetview_')
        os.close(fd)
        with open(path, 'wb') as f:
            f.write(resp.content)
        return path
    except Exception as e:
        logger.warning(f"[Inclusão] Street View erro: {e}")
    return None


def formatar_cep(cep: str) -> str:
    """Formato: xxxxx-xxx"""
    c = _limpar_cep(cep)
    if len(c) == 8:
        return f"{c[:5]}-{c[5:]}"
    return c


# Debug: DEBUG_INCLUSAO_FORM=1 no .env para log detalhado por etapa
DEBUG_FORM = os.environ.get('DEBUG_INCLUSAO_FORM', '').lower() in ('1', 'true', 'yes')


def _log_step(step: str, msg: str = '', ok: bool = True):
    """Log de etapa para debug do preenchimento do formulário."""
    if DEBUG_FORM or not ok:
        level = logger.info if ok else logger.warning
        level(f"[Inclusão] {step} {'✓' if ok else '✗'} {msg}".strip())


def _fill_safe(page, locator, valor: str, step_name: str, timeout: int = 8000) -> bool:
    """Preenche campo com timeout reduzido e log. Retorna True se OK."""
    try:
        el = page.locator(locator)
        n = el.count()
        _log_step(step_name, f"elementos={n}")
        if n > 0:
            el.first.fill(str(valor), timeout=timeout)
            _log_step(step_name, "preenchido", ok=True)
            return True
    except Exception as e:
        _log_step(step_name, str(e), ok=False)
    return False


def _preencher_campo(page, locator, valor: str) -> bool:
    """Preenche campo e retorna True se OK."""
    try:
        el = page.locator(locator).first
        if el.count() > 0:
            el.fill(str(valor), timeout=8000)
            return True
    except Exception:
        pass
    return False


def _clicar_opcao(page, texto: str) -> bool:
    """Clica em opção (radio) que contém o texto exato."""
    try:
        el = page.get_by_text(texto, exact=True).first
        if el.count() > 0:
            el.click()
            return True
    except Exception:
        pass
    try:
        el = page.locator(f'span.aDTYNe:has-text("{texto}")').first
        if el.count() > 0:
            el.click()
            return True
    except Exception:
        pass
    return False


def _resolver_accountchooser_google(page) -> bool:
    """
    Se estiver na tela 'Choose an account', tenta selecionar GOOGLE_FORM_LOGIN_EMAIL.
    Retorna True se saiu do accountchooser (ou não estava nele).
    """
    url = page.url or ""
    if "accountchooser" not in url:
        return True

    email = _email_login_google()
    logger.warning("[Inclusão] Google pediu accountchooser; tentando conta de login %s", email)

    # Conta alvo (login)
    for sel in [
        f'div[data-identifier="{email}"]',
        f'[data-email="{email}"]',
        f'text={email}',
    ]:
        loc = page.locator(sel)
        if loc.count() > 0:
            try:
                loc.first.click(timeout=5000)
                page.wait_for_timeout(3000)
                if "accountchooser" not in (page.url or ""):
                    return True
            except Exception as e:
                logger.warning("[Inclusão] Clique na conta %s falhou: %s", email, e)

    # Conta errada / signed out → "Use another account"
    for texto in ("Use another account", "Usar outra conta"):
        btn = page.get_by_text(texto, exact=False)
        if btn.count() > 0:
            try:
                btn.first.click(timeout=5000)
                page.wait_for_timeout(2000)
                logger.info("[Inclusão] Clicou em '%s'", texto)
                return "accountchooser" not in (page.url or "")
            except Exception:
                pass

    try:
        body = (page.inner_text("body") or "")[:400]
        logger.warning(
            "[Inclusão] accountchooser sem a conta esperada. Trecho: %s",
            body.replace("\n", " | ")[:300],
        )
    except Exception:
        pass
    return False


def _fazer_login_google(page) -> bool:
    """
    Se a página redirecionou para login do Google, autentica com
    GOOGLE_FORM_LOGIN_EMAIL / GOOGLE_FORM_LOGIN_PASSWORD (conta dona do form).
    GOOGLE_FORM_EMAIL é só o valor do campo e-mail dentro do formulário.
    """
    if _esta_no_formulario(page):
        return True
    if "accounts.google.com" not in (page.url or ""):
        return True

    if "accountchooser" in (page.url or ""):
        _resolver_accountchooser_google(page)
        if _esta_no_formulario(page):
            return True
        page.wait_for_timeout(1000)

    email = _email_login_google()
    password = _senha_login_google()
    if not password:
        logger.warning(
            "[Inclusão] Sem sessão salva e senha de login vazia "
            "(GOOGLE_FORM_LOGIN_PASSWORD / GOOGLE_FORM_PASSWORD). "
            "Rode: python scripts/salvar_sessao_google_form.py"
        )
        return False
    try:
        def _clicar_avancar():
            for selector in [
                'button:has-text("Avançar")',
                'button:has-text("Next")',
                'span:has-text("Avançar")',
                'span:has-text("Next")',
                '[role="button"]:has-text("Avançar")',
                '[role="button"]:has-text("Next")',
            ]:
                btn = page.locator(selector).first
                if btn.count() > 0:
                    btn.click()
                    return True
            return False

        def _pular_passkey():
            for texto in ['Agora não', 'Not now', 'Agora nao']:
                try:
                    btn = page.get_by_role('button', name=texto)
                    if btn.count() > 0:
                        btn.first.click(force=True, timeout=3000)
                        logger.info(f"[Inclusão] Clicou em '{texto}' (passkey)")
                        return True
                except Exception:
                    pass
            for texto in ['Agora não', 'Not now']:
                try:
                    btn = page.get_by_text(texto, exact=False)
                    if btn.count() > 0:
                        btn.first.click(force=True, timeout=3000)
                        logger.info(f"[Inclusão] Clicou em '{texto}' (get_by_text)")
                        return True
                except Exception:
                    pass
            for sel in [
                'button:has-text("Agora não")',
                'button:has-text("Not now")',
                'span:has-text("Agora não")',
                'span:has-text("Not now")',
                '[role="button"]:has-text("Agora não")',
                '[role="button"]:has-text("Not now")',
                'div[role="button"]:has-text("Agora não")',
                'div[role="button"]:has-text("Not now")',
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0:
                        btn.click(force=True, timeout=3000)
                        logger.info(f"[Inclusão] Clicou em passkey via seletor {sel[:40]}")
                        return True
                except Exception:
                    pass
            return False

        email_input = page.locator('#identifierId').first
        if email_input.count() > 0:
            email_input.click()
            page.wait_for_timeout(300)
            email_input.fill(email)
            page.wait_for_timeout(500)
            _clicar_avancar()
            page.wait_for_timeout(3000)

        if 'passkeyenrollment' in page.url or page.locator('text=Login mais rápido').count() > 0:
            if _pular_passkey():
                page.wait_for_timeout(2000)

        password_input = page.locator('input[type="password"]:not([aria-hidden="true"])').first
        if password_input.count() == 0:
            password_input = page.locator('input[name="Passwd"], input[name="password"]').first
        if password_input.count() > 0:
            password_input.click()
            page.wait_for_timeout(300)
            password_input.fill(password)
            page.wait_for_timeout(500)
            _clicar_avancar()
            page.wait_for_timeout(5000)
            page.wait_for_load_state('networkidle', timeout=10000)

        for tentativa in range(5):
            page.wait_for_timeout(2000)
            if _esta_no_formulario(page) or "accounts.google.com" not in page.url:
                logger.info(f"[Inclusão] Saiu do login (tentativa {tentativa + 1})")
                break
            if "accountchooser" in (page.url or ""):
                _resolver_accountchooser_google(page)
            try:
                page.get_by_text("Agora não", exact=False).first.wait_for(state='visible', timeout=3000)
            except Exception:
                try:
                    page.get_by_text("Not now", exact=False).first.wait_for(state='visible', timeout=1000)
                except Exception:
                    pass
            if _pular_passkey():
                page.wait_for_timeout(3000)
        if "accounts.google.com" in page.url:
            logger.warning(
                "[Inclusão] Ainda em accounts.google.com após tentativas (url=%s)",
                (page.url or "")[:120],
            )
            return False
    except Exception as e:
        logger.warning(f"[Inclusão] Erro no login Google: {e}")
        return False
    return True


def _mensagem_sessao_google_invalida(page_url: str = "") -> str:
    login = _email_login_google()
    return (
        "Não foi possível abrir o formulário Google: sessão inválida ou expirada. "
        f"Faça login com *{login}* rodando localmente:\n"
        "`python scripts/salvar_sessao_google_form.py`\n"
        "Depois: `python scripts/publicar_sessao_google_railway.py`"
        + (f"\n(URL: {page_url[:80]}...)" if page_url else "")
    )


# Seletor para inputs de texto do formulário - EXCLUI o campo do reCAPTCHA (name="ca", aria-label com "ouve")
INPUTS_TEXT_FORM = 'input[type="text"]:not([name="ca"]):not([aria-label*="ouve"])'
# Campos de texto longo (Cidade, Logradouro, etc): Google Forms usa textarea OU div contenteditable
TEXTAREAS_FORM = 'textarea:not([name="g-recaptcha-response"])'
# Fallback: Google Forms Material Design usa div[contenteditable] e [role="textbox"]
CONTENTEDITABLE_FORM = 'div[contenteditable="true"], [role="textbox"]'


def _dropdown_valor_selecionado(page, nth_dropdown: int) -> str:
    """Retorna o data-value da opção selecionada no listbox nth, ou ''."""
    try:
        lbs = page.locator('div[role="listbox"]')
        if lbs.count() <= nth_dropdown:
            return ""
        sel = lbs.nth(nth_dropdown).locator('[role="option"][aria-selected="true"]').first
        if sel.count() == 0:
            return ""
        return (sel.get_attribute("data-value") or sel.inner_text() or "").strip()
    except Exception:
        return ""


def _selecionar_dropdown(page, valor: str, nth_dropdown: int = 0) -> bool:
    """
    Abre o listbox pelo índice (0=Executivo, 1=Empresa, 2=UF) e seleciona o valor.

    Importante: no Google Forms as opções ficam no DOM mesmo com o menu fechado.
    Clicar com force=True em opção oculta NÃO seleciona — precisa abrir o listbox.
    """
    valor = (valor or "").strip()
    if not valor:
        return False

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

        listboxes = page.locator('div[role="listbox"]')
        n_lb = listboxes.count()
        if n_lb <= nth_dropdown:
            _log_step(
                "Dropdown",
                f"listbox nth={nth_dropdown} inexistente (total={n_lb})",
                ok=False,
            )
            return False

        lb = listboxes.nth(nth_dropdown)
        lb.scroll_into_view_if_needed()
        page.wait_for_timeout(200)

        # Já selecionado?
        atual = _dropdown_valor_selecionado(page, nth_dropdown)
        if atual and atual.casefold() == valor.casefold():
            _log_step("Dropdown", f"{valor} (já selecionado)", ok=True)
            return True

        # Abrir listbox (clicar no trigger / no próprio listbox)
        expanded = (lb.get_attribute("aria-expanded") or "").lower() == "true"
        if not expanded:
            # Preferir o span "Escolher" / valor atual dentro deste listbox
            trigger = lb.locator('span.vRMGwf.oJeWuf, [role="option"][aria-selected="true"]').first
            try:
                if trigger.count() > 0:
                    trigger.click(timeout=5000)
                else:
                    lb.click(timeout=5000)
            except Exception:
                lb.click(force=True, timeout=5000)
            page.wait_for_timeout(600)

        # Opção DENTRO deste listbox (nunca buscar na página inteira)
        candidatos = [
            f'[role="option"][data-value="{valor}"]',
            f'[role="option"][data-value="{valor.upper()}"]',
            f'[role="option"][data-value="{valor.lower()}"]',
        ]
        opt = None
        for sel in candidatos:
            loc = lb.locator(sel)
            if loc.count() > 0:
                opt = loc.first
                break
        if opt is None:
            # Match por texto exato (case-insensitive via filter)
            loc = lb.locator('[role="option"]').filter(has_text=re.compile(rf"^{re.escape(valor)}$", re.I))
            if loc.count() > 0:
                opt = loc.first

        if opt is None:
            _log_step("Dropdown", f"Opção '{valor}' não encontrada no listbox {nth_dropdown}", ok=False)
            page.keyboard.press("Escape")
            return False

        opt.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        try:
            opt.click(timeout=5000)
        except Exception:
            opt.click(force=True, timeout=5000)
        page.wait_for_timeout(500)

        # Fechar se ainda aberto
        if (lb.get_attribute("aria-expanded") or "").lower() == "true":
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

        selecionado = _dropdown_valor_selecionado(page, nth_dropdown)
        ok = bool(selecionado) and selecionado.casefold() == valor.casefold()
        _log_step(
            "Dropdown",
            f"nth={nth_dropdown} pediu='{valor}' ficou='{selecionado}'",
            ok=ok,
        )
        return ok
    except Exception as e:
        logger.warning(f"[Inclusão] Dropdown '{valor}' (nth={nth_dropdown}) erro: {e}")
        _log_step("Dropdown", str(e), ok=False)
        return False


def _limpar_formulario_google(page) -> bool:
    """
    Clica em 'Limpar formulário' e confirma o diálogo.
    Com conta logada o Forms reabre com rascunho da tentativa anterior;
    limpar evita misturar dados/arquivos antigos com a solicitação atual.
    """
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

        link = page.get_by_text(re.compile(r"^Limpar formul[aá]rio$|^Clear form$", re.I)).first
        if link.count() == 0:
            link = page.locator('span:has-text("Limpar formulário"), span:has-text("Clear form")').first
        if link.count() == 0:
            _log_step("0-Limpar", "Link Limpar formulário não encontrado", ok=False)
            return False

        link.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        link.click(timeout=5000)
        page.wait_for_timeout(1000)

        # Diálogo: botão de confirmação (não o Cancelar)
        dialog = page.locator('[role="dialog"], [role="alertdialog"], div[aria-modal="true"]')
        confirm = None
        if dialog.count() > 0:
            d = dialog.last
            for sel in [
                'span:has-text("Limpar formulário")',
                'span:has-text("Clear form")',
                'button:has-text("Limpar formulário")',
                'button:has-text("Clear form")',
                '[role="button"]:has-text("Limpar")',
                '[role="button"]:has-text("Clear")',
            ]:
                btn = d.locator(sel).filter(has_not_text=re.compile(r"Cancel|Cancelar", re.I))
                if btn.count() > 0:
                    confirm = btn.last
                    break
        if confirm is None:
            # Fallback na página
            confirm = page.locator(
                'div[role="dialog"] span:has-text("Limpar formulário"), '
                'div[role="dialog"] button:has-text("Limpar formulário")'
            ).last

        if confirm is not None and confirm.count() > 0:
            confirm.click(timeout=5000)
            page.wait_for_timeout(1500)
            _log_step("0-Limpar", "OK (confirmado)")
            return True

        _log_step("0-Limpar", "Clicou no link, mas diálogo de confirmação não apareceu", ok=False)
        return False
    except Exception as e:
        _log_step("0-Limpar", str(e), ok=False)
        return False


def _fechar_picker_modal(page) -> None:
    """
    Fecha o modal do Google Picker (Inserir arquivo) que bloqueia cliques.
    Quando o upload falha, o modal fica aberto e intercepta o botão Enviar.
    """
    try:
        # 1) Clicar em Cancelar/Fechar no picker (dentro do iframe)
        try:
            picker = page.frame_locator('iframe[src*="docs.google.com/picker"]')
            for texto in ['Cancelar', 'Cancel', 'Fechar', 'Close']:
                btn = picker.locator(f'button:has-text("{texto}"), span:has-text("{texto}")').first
                if btn.count() > 0:
                    btn.click(force=True, timeout=2000)
                    page.wait_for_timeout(500)
                    logger.info(f"[Inclusão] Fechou picker via '{texto}'")
                    return
        except Exception:
            pass
        # 2) Tecla Escape (fecha modais)
        for _ in range(3):
            page.keyboard.press('Escape')
            page.wait_for_timeout(400)
        # 3) Clicar fora do modal (se houver overlay)
        try:
            page.locator('.picker-dialog, [role="dialog"]').first.click(position={'x': 0, 'y': 0})
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[Inclusão] _fechar_picker_modal: {e}")


def _upload_arquivos_viabilidade(page, arquivos_paths: list) -> bool:
    """
    Faz upload de um ou mais arquivos no formulário Google Forms.

    Fluxo que funciona com sessão Google autenticada:
    1) Clicar em "Adicionar arquivo" (abre Google Picker em iframe)
    2) set_input_files no input[type=file] oculto DENTRO do iframe do picker
       (não depende do filechooser nativo, que costuma falhar no Playwright)
    """
    if not arquivos_paths:
        return False
    paths_abs = []
    for p in arquivos_paths:
        pa = os.path.abspath(str(p))
        if os.path.isfile(pa):
            paths_abs.append(pa)
    if not paths_abs:
        _log_step("16-Foto", "Nenhum arquivo válido encontrado", ok=False)
        return False

    def _tem_anexo_na_pagina() -> bool:
        """Indícios de que o Forms aceitou o(s) arquivo(s)."""
        nomes = [os.path.basename(p) for p in paths_abs]
        for nome in nomes:
            stem = os.path.splitext(nome)[0]
            for trecho in (nome, stem, ".jpg", ".jpeg", ".png", ".pdf"):
                if trecho and page.locator(f"text={trecho}").count() > 0:
                    return True
        for trecho in ("Remover arquivo", "Remove file", "1 arquivo", "arquivos"):
            if page.locator(f"text={trecho}").count() > 0:
                return True
        return False

    def _set_files_em_frames(paths: list) -> bool:
        """Procura input[type=file] em todos os frames e aplica set_input_files."""
        for frame in page.frames:
            try:
                fi = frame.locator('input[type="file"]')
                if fi.count() == 0:
                    continue
                fi.first.set_input_files(paths, timeout=10000)
                _log_step(
                    "16-Foto",
                    f"set_input_files em frame ({len(paths)} arquivo(s)) url={frame.url[:60]}",
                )
                return True
            except Exception as e:
                _log_step("16-Foto", f"frame {frame.url[:40]}: {e}", ok=False)
        return False

    # 1) Input direto na página (raro no Forms moderno, mas barato tentar)
    try:
        fi = page.locator('input[type="file"]')
        if fi.count() > 0:
            fi.first.set_input_files(paths_abs, timeout=8000)
            page.wait_for_timeout(2000)
            if _tem_anexo_na_pagina():
                _log_step("16-Foto", f"OK (input direto, {len(paths_abs)} arquivo(s))")
                return True
    except Exception as e:
        _log_step("16-Foto", f"input direto: {e}", ok=False)

    # 2) Abrir Google Picker via "Adicionar arquivo"
    btn_add = page.locator('span.NPEfkd.RveJvd.snByac:has-text("Adicionar arquivo")').first
    if btn_add.count() == 0:
        btn_add = page.get_by_role("button", name=re.compile(r"Adicionar arquivo|Add file", re.I)).first
    if btn_add.count() == 0:
        btn_add = page.get_by_text("Adicionar arquivo", exact=False).first
    if btn_add.count() == 0:
        _log_step("16-Foto", "Botão Adicionar arquivo não encontrado", ok=False)
        return False

    try:
        btn_add.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        # Às vezes o clique já dispara filechooser (sem picker)
        try:
            with page.expect_file_chooser(timeout=2500) as fc_info:
                btn_add.click(timeout=5000)
            fc_info.value.set_files(paths_abs)
            page.wait_for_timeout(2500)
            if _tem_anexo_na_pagina():
                _log_step("16-Foto", f"OK (filechooser no botão, {len(paths_abs)} arquivo(s))")
                return True
        except Exception:
            # Picker modal esperado
            pass

        # Aguardar iframe do picker
        try:
            page.wait_for_selector(
                'iframe[src*="docs.google.com/picker"], iframe[src*="picker"]',
                timeout=8000,
            )
        except Exception:
            pass
        page.wait_for_timeout(1500)

        # Estratégia principal: input oculto dentro do iframe do picker
        if _set_files_em_frames(paths_abs):
            page.wait_for_timeout(3000)
            if _tem_anexo_na_pagina():
                _log_step("16-Foto", f"OK (picker iframe input, {len(paths_abs)} arquivo(s))")
                return True
            # Às vezes o picker precisa de confirmação / espera extra
            page.wait_for_timeout(3000)
            if _tem_anexo_na_pagina():
                _log_step("16-Foto", f"OK (picker iframe, delay extra, {len(paths_abs)} arquivo(s))")
                return True

        # Fallback: botão Procurar/Browse + filechooser
        try:
            picker = page.frame_locator(
                'iframe[src*="docs.google.com/picker"], iframe[src*="picker"]'
            )
            for sel in [
                '[jsname="V67aGc"]',
                'span.UywwFc-vQzf8d:has-text("Procurar")',
                'span:has-text("Procurar")',
                'button:has-text("Procurar")',
                'button:has-text("Browse")',
                '[role="button"]:has-text("Procurar")',
                '[role="button"]:has-text("Browse")',
            ]:
                btn_procurar = picker.locator(sel).first
                if btn_procurar.count() == 0:
                    continue
                try:
                    btn_procurar.wait_for(state="visible", timeout=4000)
                    with page.expect_file_chooser(timeout=12000) as fc_info:
                        btn_procurar.click(force=True)
                    fc_info.value.set_files(paths_abs)
                    page.wait_for_timeout(3000)
                    if _tem_anexo_na_pagina():
                        _log_step("16-Foto", f"OK (Procurar+filechooser, {len(paths_abs)} arquivo(s))")
                        return True
                except Exception as e_fc:
                    _log_step("16-Foto", f"Procurar {sel[:30]}: {e_fc}", ok=False)
        except Exception as e_picker:
            _log_step("16-Foto", f"picker fallback: {e_picker}", ok=False)

    except Exception as e:
        _log_step("16-Foto", f"fluxo Adicionar arquivo: {e}", ok=False)

    _log_step("16-Foto", "Todas as estratégias de upload falharam", ok=False)
    return False


def _proximo_protocolo_inclusao(uploader, base_folder: str) -> str:
    """
    Gera protocolo AAAAMMDDHHMMX (X começa em 1 e sobe no mesmo minuto).
    Ex.: 2026072222371, 2026072222372, ...
    Consulta pastas já existentes no R2 com o mesmo prefixo de data/hora.
    """
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d%H%M")
    max_seq = 0
    try:
        # Chaves: {R2_FOLDER_ROOT}/{base_folder}/{protocolo}/arquivo
        root = (uploader.folder_root or "").strip("/")
        parts = [p for p in (root, base_folder.strip("/"), stamp) if p]
        list_prefix = "/".join(parts)
        token = None
        while True:
            kwargs = {
                "Bucket": uploader.bucket_name,
                "Prefix": list_prefix,
                "Delimiter": "/",
                "MaxKeys": 1000,
            }
            if token:
                kwargs["ContinuationToken"] = token
            resp = uploader._client.list_objects_v2(**kwargs)
            for cp in resp.get("CommonPrefixes") or []:
                pref = (cp.get("Prefix") or "").rstrip("/")
                nome = pref.split("/")[-1]
                m = re.fullmatch(rf"{re.escape(stamp)}(\d+)", nome)
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
    except Exception as e:
        logger.warning("[Inclusão] Não foi possível listar protocolos no R2 (%s); usando X=1", e)
        max_seq = 0

    return f"{stamp}{max_seq + 1}"


def _upload_inclusao_r2(dados: dict, arquivos_paths: list) -> tuple:
    """
    Salva os arquivos da inclusão em pasta do R2 (uma pasta por solicitação).
    Pasta: Inclusao_Viabilidade/{protocolo AAAAMMDDHHMMX}/
    Retorna (sucesso: bool, pasta_path: str, links: list[dict], protocolo: str)
    links: [{"url": "...", "nome": "foto_1.jpg"}, ...]
    """
    from crm_app.cloudflare_r2_service import CloudflareR2Storage

    base_folder = getattr(settings, "INCLUSAO_R2_FOLDER", "Inclusao_Viabilidade")
    uploader = CloudflareR2Storage()
    protocolo = (dados.get("protocolo") or "").strip()
    if not protocolo:
        protocolo = _proximo_protocolo_inclusao(uploader, base_folder)
    folder_path = f"{base_folder}/{protocolo}"

    links: list = []
    for i, path in enumerate(arquivos_paths):
        if not path or not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1] or ".jpg"
        nome = f"foto_{i + 1}{ext}" if i == 0 else f"comprovante_{i}{ext}"
        try:
            with open(path, "rb") as f:
                url = uploader.upload_file(f, folder_path, nome)
                if url:
                    links.append({"url": url, "nome": nome})
                    logger.info(f"[Inclusão] R2: {folder_path}/{nome} -> {url[:80]}...")
        except Exception as e:
            logger.warning(f"[Inclusão] Erro ao subir {nome} para R2: {e}")
    return len(links) > 0, folder_path, links, protocolo


def montar_payload_formulario_inclusao(
    dados: dict,
    protocolo: str,
    arquivos: Optional[list] = None,
) -> dict:
    """
    Monta o payload consumido pela extensão Chrome para preencher o Google Forms.
    """
    viacep = dados.get("viacep") or {}
    uf_sigla = (viacep.get("uf") or "").upper()
    logradouro = viacep.get("logradouro", "") or ""
    observacoes = (dados.get("observacoes") or "").strip()
    prefixo = f"Protocolo: {protocolo}"
    obs_final = f"{prefixo}\n{observacoes}".strip() if observacoes else prefixo

    arquivos_norm: list = []
    for item in arquivos or []:
        if isinstance(item, dict) and item.get("url"):
            arquivos_norm.append(
                {
                    "url": item["url"],
                    "nome": item.get("nome") or "arquivo.jpg",
                }
            )
        elif isinstance(item, str) and item:
            arquivos_norm.append({"url": item, "nome": item.rsplit("/", 1)[-1] or "arquivo.jpg"})

    return {
        "form_url": FORM_URL,
        "protocolo": protocolo,
        "codigo_sap": CODIGO_SAP,
        "executivo": EXECUTIVO,
        "tipo_canal": TIPO_CANAL,
        "email": _email_formulario(),
        "empresa": EMPRESA_VENDAS,
        "uf_sigla": uf_sigla,
        "uf": UF_SIGLA_PARA_NOME.get(uf_sigla, uf_sigla),
        "cep": formatar_cep(dados.get("cep", "")),
        "cidade": viacep.get("localidade", "") or "",
        "tipo_logradouro": obter_tipo_logradouro(logradouro),
        "logradouro": logradouro,
        "numero": str(dados.get("numero_fachada", "") or "0"),
        "bairro": viacep.get("bairro", "") or "",
        "complementos": dados.get("complementos", "") or "sem complementos",
        "fachadas_vizinhos": dados.get("fachadas_vizinhos", "") or "",
        "coordenadas": dados.get("coordenadas", "") or "",
        "observacoes": obs_final,
        "arquivos": arquivos_norm,
    }


def criar_demanda_inclusao(
    dados: dict,
    arquivos_paths: Optional[list] = None,
    *,
    telefone_solicitante: str = "",
    solicitante=None,
) -> Tuple[bool, str]:
    """
    Persiste a solicitação para a Auditoria (sem preencher o Google Forms no servidor).
    Sobe arquivos no R2 e cria DemandaInclusaoViabilidade.
    """
    from crm_app.models import DemandaInclusaoViabilidade

    paths = [p for p in (arquivos_paths or []) if p and os.path.isfile(p)]
    if not paths:
        return False, "Nenhum arquivo anexado (foto/comprovante) para criar a demanda."

    try:
        ok_r2, folder_path, links, protocolo = _upload_inclusao_r2(dados, paths)
    except Exception as e:
        logger.exception("[Inclusão] Falha no upload R2 ao criar demanda: %s", e)
        return False, f"Falha ao salvar anexos no R2: {e}"

    if not ok_r2 or not protocolo:
        return False, "Não foi possível salvar os anexos no R2."

    payload = montar_payload_formulario_inclusao(dados, protocolo, links)
    snapshot = {
        "cep": dados.get("cep"),
        "viacep": dados.get("viacep") or {},
        "numero_fachada": dados.get("numero_fachada"),
        "complementos": dados.get("complementos"),
        "fachadas_vizinhos": dados.get("fachadas_vizinhos"),
        "coordenadas": dados.get("coordenadas"),
        "observacoes": dados.get("observacoes") or "",
    }

    demanda = DemandaInclusaoViabilidade.objects.create(
        protocolo=protocolo,
        status=DemandaInclusaoViabilidade.STATUS_PENDENTE,
        telefone_solicitante=(telefone_solicitante or "")[:30],
        solicitante=solicitante if getattr(solicitante, "pk", None) else None,
        dados=snapshot,
        form_payload=payload,
        arquivos_urls=links,
        r2_folder=folder_path or "",
        observacoes=payload.get("observacoes") or "",
    )

    msg = (
        "✅ Solicitação registrada na *Auditoria* para envio ao Google Forms.\n\n"
        f"📋 *Protocolo:* `{protocolo}`\n"
        f"🆔 Demanda #{demanda.id}\n\n"
        "Um auditor abrirá o pedido localmente (extensão Chrome) e anexará os arquivos."
    )
    logger.info(
        "[Inclusão] Demanda #%s criada protocolo=%s solicitante=%s",
        demanda.id,
        protocolo,
        telefone_solicitante,
    )
    return True, msg


def preencher_formulario_inclusao(
    dados: dict,
    foto_path: Optional[str] = None,
    arquivos_paths: Optional[list] = None,
) -> Tuple[bool, str]:
    """
    Preenche o formulário Google Forms de solicitação de viabilidade via Playwright.
    dados: dict com viacep, numero_fachada, complementos, fachadas_vizinhos, coordenadas, observacoes
    foto_path: (legado) caminho da foto principal
    arquivos_paths: lista de caminhos [foto, comprovante1, comprovante2, ...] - foto primeiro, depois comprovantes

    Retorna (sucesso, mensagem)
    """
    if not HAS_PLAYWRIGHT:
        return False, "Playwright não disponível"

    viacep = dados.get('viacep') or {}
    uf = viacep.get('uf', '')
    cidade = viacep.get('localidade', '')
    logradouro = viacep.get('logradouro', '')
    bairro = viacep.get('bairro', '')
    cep = dados.get('cep', '')
    numero = str(dados.get('numero_fachada', '') or '0')
    complementos = dados.get('complementos', '') or 'sem complementos'
    fachadas_vizinhos = dados.get('fachadas_vizinhos', '')
    coordenadas = dados.get('coordenadas', '')
    observacoes = dados.get('observacoes', '') or ''

    tipo_logradouro = obter_tipo_logradouro(logradouro)
    cep_formatado = formatar_cep(cep)

    headless = getattr(settings, 'PAP_HEADLESS', True)
    _garantir_storage_state_arquivo()
    state_path = _caminho_storage_state()
    tem_sessao = os.path.isfile(state_path)

    od_pasta_used = None
    protocolo_inclusao = None
    browser = None
    context = None
    try:
        with sync_playwright() as p:
            launch_opts = {"headless": headless}
            if headless:
                launch_opts["args"] = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            browser = p.chromium.launch(**launch_opts)
            context_kwargs = {
                "viewport": {"width": 1280, "height": 900},
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if tem_sessao:
                context_kwargs["storage_state"] = state_path
                logger.info("[Inclusão] Usando storage state: %s", state_path)
            else:
                logger.warning(
                    "[Inclusão] Sem storage state em %s — tentará login por senha. "
                    "Recomendado: python scripts/salvar_sessao_google_form.py",
                    state_path,
                )
            context = browser.new_context(**context_kwargs)
            if headless:
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )
            page = context.new_page()
            page.set_default_timeout(20000)

            page.goto(FORM_URL, wait_until='domcontentloaded')
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1500)

            # Se a sessão salva expirou, cai no login por senha (fallback)
            if not _esta_no_formulario(page):
                if tem_sessao:
                    logger.warning("[Inclusão] Sessão salva não abriu o form — tentando login e invalidando state")
                    _invalidar_storage_state()
                if not _fazer_login_google(page):
                    url_fail = ""
                    try:
                        url_fail = page.url or ""
                    except Exception:
                        pass
                    browser.close()
                    return False, _mensagem_sessao_google_invalida(url_fail)
                page.wait_for_timeout(1500)
                if not _esta_no_formulario(page):
                    page.goto(FORM_URL, wait_until='domcontentloaded')
                    try:
                        page.wait_for_load_state('networkidle', timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1500)
                if not _esta_no_formulario(page):
                    url_final = page.url
                    browser.close()
                    return False, _mensagem_sessao_google_invalida(url_final)
                # Login OK — persistir cookies para as próximas execuções
                _salvar_storage_state(context)
            else:
                # Sessão válida — renovar arquivo (cookies atualizados)
                _salvar_storage_state(context)

            # Limpar rascunho da sessão Google (dados/arquivos de tentativas anteriores)
            _limpar_formulario_google(page)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            # Inputs de texto do formulário (exclui reCAPTCHA - name="ca")
            inputs_text = page.locator(INPUTS_TEXT_FORM)
            textareas = page.locator(TEXTAREAS_FORM)
            contenteditables = page.locator(CONTENTEDITABLE_FORM)
            n_inputs = inputs_text.count()
            n_textareas = textareas.count()
            n_ce = contenteditables.count()
            _log_step("INIT", f"URL={page.url[:80]}... inputs={n_inputs} textareas={n_textareas} contenteditable={n_ce}")

            if n_inputs < 1 and n_textareas < 1 and n_ce < 1:
                browser.close()
                return False, "Formulário aberto, mas nenhum campo editável foi encontrado (layout mudou?)."

            # Ordem do formulário (manter alinhado):
            #  1) Código SAP   2) Executivo   3) Tipo canal   4) E-mail   5) Empresa
            #  6) UF/Estado   7) CEP         8) Cidade       9) Tipo logradouro
            # 10) Nome logradouro  11) Nº fachada  12) Bairro  13) Complementos
            # 14) Fachadas vizinhos  15) Coordenadas  16) Foto/vídeo  17) Observações

            email_campo = _email_formulario()

            def _fill_textlike(idx: int, valor: str, step_name: str) -> bool:
                """Preenche campo de texto longo (textarea OU div contenteditable). Google Forms pode usar ambos."""
                val = str(valor)
                # 1) Tentar textarea
                if textareas.count() > idx:
                    try:
                        textareas.nth(idx).fill(val, timeout=8000)
                        _log_step(step_name, "OK (textarea)")
                        return True
                    except Exception as e:
                        _log_step(step_name, f"textarea: {e}", ok=False)
                # 2) Fallback: div contenteditable / role=textbox
                if contenteditables.count() > idx:
                    try:
                        el = contenteditables.nth(idx)
                        el.click()
                        page.wait_for_timeout(200)
                        el.fill(val, timeout=8000)
                        _log_step(step_name, "OK (contenteditable)")
                        return True
                    except Exception as e:
                        _log_step(step_name, f"contenteditable: {e}", ok=False)
                _log_step(step_name, f"textareas={n_textareas}, contenteditable={n_ce}, idx={idx}", ok=False)
                return False

            # 1. Código SAP
            _log_step("1-CodigoSAP", f"inputs={n_inputs}")
            if n_inputs >= 1:
                try:
                    inputs_text.first.fill(CODIGO_SAP, timeout=8000)
                except Exception as e:
                    _log_step("1-CodigoSAP", str(e), ok=False)
                    raise
            page.wait_for_timeout(200)

            # 2. Executivo - dropdown (índice 0)
            _log_step("2-Executivo", "")
            ok_dd = _selecionar_dropdown(page, EXECUTIVO, nth_dropdown=0)
            _log_step("2-Executivo", "OK" if ok_dd else "FALHOU", ok=ok_dd)
            page.wait_for_timeout(500)

            # 3. Tipo canal - radio PAP
            _log_step("3-TipoCanal", "")
            _clicar_opcao(page, TIPO_CANAL)
            page.wait_for_timeout(200)

            # 4. E-mail
            _log_step("4-Email", "")
            try:
                page.locator('input[type="email"]').first.fill(email_campo, timeout=8000)
            except Exception as e:
                _log_step("4-Email", str(e), ok=False)
                raise
            page.wait_for_timeout(200)

            # 5. Empresa - dropdown (índice 1)
            _log_step("5-Empresa", "")
            _selecionar_dropdown(page, EMPRESA_VENDAS, nth_dropdown=1)
            page.wait_for_timeout(500)

            # 6. UF - dropdown (índice 2; ViaCEP retorna sigla "MG", form usa "Minas Gerais")
            if uf:
                uf_form = UF_SIGLA_PARA_NOME.get(uf.upper(), uf)
                _log_step("6-UF", f"{uf} -> {uf_form}")
                _selecionar_dropdown(page, uf_form, nth_dropdown=2)
                page.wait_for_timeout(500)

            # 7. CEP
            _log_step("7-CEP", "")
            if n_inputs >= 2:
                try:
                    inputs_text.nth(1).fill(cep_formatado, timeout=8000)
                except Exception as e:
                    _log_step("7-CEP", str(e), ok=False)
            page.wait_for_timeout(200)

            # 8. Cidade
            _log_step("8-Cidade", "")
            _fill_textlike(0, cidade, "8-Cidade")
            page.wait_for_timeout(200)

            # 9. Tipo logradouro - radio
            _log_step("9-TipoLogradouro", tipo_logradouro)
            _clicar_opcao(page, tipo_logradouro)
            page.wait_for_timeout(200)

            # 10. Nome logradouro
            _fill_textlike(1, logradouro, "10-Logradouro")
            page.wait_for_timeout(200)

            # 11. Número fachada
            _log_step("11-Numero", "")
            if n_inputs >= 3:
                try:
                    inputs_text.nth(2).fill(numero, timeout=8000)
                except Exception as e:
                    _log_step("11-Numero", str(e), ok=False)
            page.wait_for_timeout(200)

            # 12. Bairro
            _fill_textlike(2, bairro, "12-Bairro")
            page.wait_for_timeout(200)

            # 13. Complementos
            _fill_textlike(3, complementos, "13-Complementos")
            page.wait_for_timeout(200)

            # 14. Fachadas vizinhas
            _fill_textlike(4, fachadas_vizinhos, "14-FachadasVizinhos")
            page.wait_for_timeout(200)

            # 15. Coordenadas
            _log_step("15-Coordenadas", "")
            if n_inputs >= 4:
                try:
                    inputs_text.nth(3).fill(coordenadas, timeout=8000)
                except Exception as e:
                    _log_step("15-Coordenadas", str(e), ok=False)
            page.wait_for_timeout(200)

            # 16. Upload de arquivos (foto + comprovantes). Primeiro salva no R2, depois tenta no formulário
            paths = arquivos_paths if arquivos_paths else ([foto_path] if foto_path else [])
            paths = [p for p in paths if p and os.path.isfile(p)]
            ok_upload = False
            if paths:
                try:
                    ok_od, od_pasta_used, _, protocolo_inclusao = _upload_inclusao_r2(dados, paths)
                    if ok_od:
                        logger.info(
                            "[Inclusão] Arquivos salvos no R2: %s (protocolo=%s)",
                            od_pasta_used,
                            protocolo_inclusao,
                        )
                except Exception as e:
                    logger.warning(f"[Inclusão] Upload R2 falhou (continuando): {e}")
                ok_upload = _upload_arquivos_viabilidade(page, paths)
                # Se o upload falhou, o modal do Google Picker pode ter ficado aberto e bloqueia Enviar
                _fechar_picker_modal(page)
                page.wait_for_timeout(500)

            # 17. Observações - inclui protocolo quando houver
            obs_final = (observacoes or "").strip()
            if protocolo_inclusao:
                prefixo = f"Protocolo: {protocolo_inclusao}"
                obs_final = f"{prefixo}\n{obs_final}".strip() if obs_final else prefixo
            if obs_final:
                _fill_textlike(5, obs_final, "17-Observacoes")

            # Submit
            _log_step("SUBMIT", "Procurando botão Enviar...")
            submit = page.get_by_role('button', name='Enviar')
            if submit.count() == 0:
                submit = page.locator('span.NPEfkd:has-text("Enviar")').first
            if submit.count() == 0:
                submit = page.locator('span:has-text("Enviar")').first
            clicou_enviar = False
            erros_val: list = []
            if submit.count() > 0:
                _log_step("SUBMIT", "Clicando Enviar...")
                _fechar_picker_modal(page)  # Garantir que modal não bloqueie
                page.wait_for_timeout(300)
                try:
                    submit.click(timeout=15000)
                    clicou_enviar = True
                except Exception:
                    # Modal pode estar bloqueando; tentar fechar e force click
                    _fechar_picker_modal(page)
                    page.wait_for_timeout(500)
                    submit.click(force=True, timeout=10000)
                    clicou_enviar = True
                page.wait_for_timeout(5000)
                # Verificar confirmação - apenas frases específicas da página de sucesso
                # (evitar falso positivo: "registrada"/"sua resposta" podem aparecer em labels do form)
                confirm_sel = [
                    'text="Obrigado"', 'text="Respostas enviadas"',
                    'text="Sua resposta foi registrada"',
                    'text=Your response has been recorded', 'text=Thank you',
                    'text=Response recorded',
                    '[data-params*="confirmationMessage"]',
                ]
                still_has_form = page.locator('span:has-text("Enviar"), button:has-text("Enviar")').count() > 0
                confirmed = any(page.locator(s).count() > 0 for s in confirm_sel)
                if not confirmed and not still_has_form and "formResponse" in (page.url or ""):
                    confirmed = True
                if confirmed:
                    _log_step("SUBMIT", "Confirmado (Obrigado/Respostas enviadas)")
                    browser.close()
                    msg = "✅ Solicitação de viabilidade enviada com sucesso!"
                    if protocolo_inclusao:
                        msg += f"\n\n📋 *Protocolo:* `{protocolo_inclusao}`"
                    if od_pasta_used:
                        msg += f"\n\n📁 Arquivos salvos no R2: {od_pasta_used}"
                    return True, msg
                for sel in [
                    'text="Esta pergunta é obrigatória"',
                    'text="This is a required question"',
                    'text="Arquivo obrigatório"',
                    'div[role="alert"]',
                    '.freebirdFormviewerViewItemsItemErrorMessage',
                ]:
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            txt = (loc.first.inner_text(timeout=1000) or "").strip()
                            if txt:
                                erros_val.append(txt[:120])
                    except Exception:
                        pass
                if erros_val:
                    _log_step("SUBMIT", f"Validação: {erros_val[0]}", ok=False)
                elif still_has_form:
                    _log_step("SUBMIT", "Clicou Enviar mas o formulário continua na tela", ok=False)
            else:
                _log_step("SUBMIT", "Botão Enviar não encontrado", ok=False)
            # Capturar URL antes de fechar o browser (diagnóstico)
            url_atual = ""
            try:
                url_atual = page.url or ""
            except Exception:
                pass
            browser.close()
            # Formulário NÃO foi enviado - avisar o usuário
            if "accounts.google.com" in url_atual:
                msg = (
                    "O formulário não foi preenchido: ainda na tela de login. "
                    "Rode: python scripts/salvar_sessao_google_form.py"
                )
            elif clicou_enviar and erros_val:
                msg = f"O formulário não foi enviado: {erros_val[0]}"
            elif ok_upload is False and paths:
                msg = (
                    "O formulário não foi enviado. O upload automático da foto falhou "
                    "(o Google Forms pode bloquear em ambiente automatizado). "
                )
            elif clicou_enviar:
                msg = (
                    "O formulário foi preenchido e o Enviar foi clicado, mas a confirmação "
                    "não apareceu (campo obrigatório vazio ou upload pendente?)."
                )
            else:
                msg = "O formulário não foi enviado (botão Enviar não encontrado). "
            if protocolo_inclusao:
                msg += f"\n\n📋 Protocolo: {protocolo_inclusao}"
            if od_pasta_used:
                msg += f"\n\n📁 Arquivos salvos no R2: {od_pasta_used}\nVocê pode anexá-los manualmente no formulário."
            return False, msg

    except Exception as e:
        logger.exception(f"[Inclusão] Erro ao preencher formulário: {e}")
        err_text = str(e).split('\n')[0].strip()
        if len(err_text) > 150:
            err_text = err_text[:147] + "..."
        msg = f"Erro ao preencher formulário: {err_text}"
        if protocolo_inclusao:
            msg += f"\n\n📋 Protocolo: {protocolo_inclusao}"
        if od_pasta_used:
            msg += f"\n\n📁 Arquivos salvos no R2: {od_pasta_used}\nVocê pode anexá-los manualmente."
        return False, msg
