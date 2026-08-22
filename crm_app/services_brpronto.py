# crm_app/services_brpronto.py
"""
Consulta de biometria no Br Pronto PDV (ged360) via Playwright.

Fluxo: login → Relatórios → Detalhado → filtrar CPF → ler "Resultado da Análise".
Aprovado quando existir "Doc. Apto para Venda".

Importante: o GED bloqueia sessão simultânea — sempre fazer logoff (Sair / logout URL)
no finally, mesmo em erro.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import Page, sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    Page = Any  # type: ignore
    HAS_PLAYWRIGHT = False

BRPRONTO_BASE = "https://ged360.niointernet.com.br/brprontopdv"
BRPRONTO_LOGIN_URL = f"{BRPRONTO_BASE}/autenticacao/index"
BRPRONTO_LOGOUT_URL = f"{BRPRONTO_BASE}/autenticacao/logout"
STATUS_APTO_VENDA = "Doc. Apto para Venda"
DOMINIO_PADRAO = "BrPronto"

SEL = {
    "login": "#prkUsuario",
    "senha": "#desSenha",
    "dominio_hidden": "#dominio",
    "btn_acessar": "input[type='button'][value='Acessar']",
    "btn_cookie_aceitar": "#btnAceitar",
    "link_sair": "a[href*='autenticacao/logout'], a:has-text('Sair')",
    "cpf": "#cpf, input[name='num_cpf'], input[name='cpf']",
    "btn_filtrar": "input.bt-filtro[name='btnFiltrar'], input[value='Filtrar'], button:has-text('Filtrar')",
    "tabela": "#table-protocolo, table.registros-table",
}


def _normalizar_cpf(cpf: str) -> str:
    """Retorna apenas dígitos do CPF."""
    if not cpf:
        return ""
    return re.sub(r"\D", "", str(cpf))


def _accept_cookies_if_present(page: Page) -> None:
    try:
        btn = page.locator(SEL["btn_cookie_aceitar"])
        if btn.is_visible(timeout=1500):
            btn.click()
            page.wait_for_timeout(400)
    except Exception:
        pass


def _ensure_logout(page: Page) -> str:
    """
    Encerra a sessão no servidor (obrigatório: o GED bloqueia login simultâneo).
    Preferência: clicar em Sair; fallback: GET autenticacao/logout.
    """
    detalhes: List[str] = []
    clicked = False
    for ctx in [page, *getattr(page, "frames", [])]:
        try:
            loc = ctx.locator(SEL["link_sair"]).first
            if loc.is_visible(timeout=1200):
                loc.click()
                clicked = True
                detalhes.append("clicou link Sair")
                page.wait_for_timeout(1200)
                break
        except Exception:
            continue
    try:
        page.goto(BRPRONTO_LOGOUT_URL, wait_until="domcontentloaded", timeout=20000)
        detalhes.append("acessou autenticacao/logout")
        page.wait_for_timeout(800)
    except Exception as e:
        detalhes.append(f"logout URL falhou: {e}")
    if not clicked and "acessou autenticacao/logout" not in " ".join(detalhes):
        return "FALHA ao sair: " + "; ".join(detalhes)
    return "saiu: " + "; ".join(detalhes)


def _visible_text(page: Page, text: str, timeout: int = 1500) -> bool:
    try:
        return page.get_by_text(text, exact=False).first.is_visible(timeout=timeout)
    except Exception:
        return False


def _login_brpronto(
    page: Page,
    login: str,
    senha: str,
    dominio: Optional[str],
    timeout_ms: int,
) -> Optional[str]:
    """
    Realiza login. Retorna mensagem de erro ou None em sucesso.
    """
    page.goto(BRPRONTO_LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(800)
    _accept_cookies_if_present(page)

    try:
        page.locator(SEL["login"]).wait_for(state="visible", timeout=15000)
    except Exception:
        return "Página de login Br Pronto não encontrou campo de usuário."

    page.locator(SEL["login"]).fill(login)
    page.locator(SEL["senha"]).fill(senha)

    # Domínio: hidden #dominio (numérico) + UI "BrPronto"
    dominio_ui = (dominio or DOMINIO_PADRAO).strip() or DOMINIO_PADRAO
    try:
        hidden = page.locator(SEL["dominio_hidden"])
        if hidden.count():
            val = hidden.input_value()
            logger.info("[BrPronto] domínio hidden atual=%r (UI: %s)", val, dominio_ui)
    except Exception:
        pass
    try:
        ui = page.locator("text=Domínio").locator(
            "xpath=following::*[self::div or self::span or self::a][1]"
        )
        if ui.count() and dominio_ui.lower() not in (ui.first.inner_text() or "").lower():
            ui.first.click()
            page.get_by_text(dominio_ui, exact=True).click()
    except Exception:
        logger.debug("[BrPronto] Domínio mantido como está na tela")

    btn = page.locator(SEL["btn_acessar"])
    if btn.count():
        btn.first.click()
    else:
        # Fallback antigo
        alt = page.query_selector('input[type="submit"], button[type="submit"]')
        if alt:
            alt.click()
        else:
            page.keyboard.press("Enter")

    page.wait_for_timeout(2500)

    # Usuário bloqueado / sessão em uso
    if _visible_text(page, "Usuário bloqueado", 2000) or _visible_text(page, "redefinir a senha", 800):
        return (
            "Usuário Br Pronto bloqueado ou pedindo redefinição de senha. "
            "Use outra conta do pool ou redefina a senha no GED."
        )
    if _visible_text(page, "já está logado", 800) or _visible_text(page, "sessão ativa", 800):
        return (
            "Sessão Br Pronto ainda ativa em outro lugar. "
            "Aguarde o logoff ou libere o login no painel."
        )
    if _visible_text(page, "Senha inválida", 800) or _visible_text(page, "usuário ou senha", 800):
        return "Login ou senha Br Pronto inválidos."

    # Ainda na tela de autenticação / troca de senha = falha
    url = (page.url or "").lower()
    if "autenticacao" in url and ("index" in url or "alterar" in url or "senha" in url):
        if page.locator("input[name='desSenhaNovaAtual']").count():
            return "Br Pronto exige troca de senha nesta conta. Atualize a senha no cadastro após redefinir no GED."
        if page.locator(SEL["login"]).count() and page.locator(SEL["login"]).first.is_visible():
            return "Falha no login Br Pronto (permaneceu na tela de autenticação)."

    return None


def _abrir_relatorio_detalhado(page: Page) -> Optional[str]:
    """Navega Relatórios → Detalhado. Retorna erro ou None."""
    # Pode estar em iframe
    contexts = [page, *page.frames]

    def _click_menu(texto: str) -> bool:
        for ctx in contexts:
            for sel in (
                f'div.item:has-text("{texto}")',
                f'a:has-text("{texto}")',
                f'li:has-text("{texto}")',
                f'span:has-text("{texto}")',
            ):
                try:
                    loc = ctx.locator(sel).first
                    if loc.is_visible(timeout=1200):
                        loc.click()
                        page.wait_for_timeout(1200)
                        return True
                except Exception:
                    continue
            try:
                loc = ctx.get_by_text(texto, exact=True).first
                if loc.is_visible(timeout=800):
                    loc.click()
                    page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
        return False

    if not _click_menu("Relatórios"):
        return (
            "Menu Relatórios não encontrado. "
            "Perfil pode não ter acesso a relatório detalhado (use conta BO / NIVEL2_BOPAP)."
        )
    if not _click_menu("Detalhado"):
        return (
            "Submenu Detalhado não encontrado após Relatórios. "
            "Confirme que a conta tem perfil GED_BRPRONTOPDV_NIVEL2_BOPAP."
        )
    page.wait_for_timeout(1500)
    return None


def _cpf_digitos_iguais(cpf_a: str, cpf_b: str) -> bool:
    """Compara CPF/CNPJ apenas pelos dígitos (ignora máscara)."""
    a = _normalizar_cpf(cpf_a)
    b = _normalizar_cpf(cpf_b)
    if not a or not b:
        return False
    return a == b


def _preencher_cpf_e_filtrar(page: Page, cpf_limpo: str) -> Optional[str]:
    cpf_input = None
    for ctx in [page, *page.frames]:
        try:
            loc = ctx.locator(SEL["cpf"]).first
            if loc.is_visible(timeout=2000):
                cpf_input = loc
                break
        except Exception:
            continue
    if not cpf_input:
        # Fallback por label
        try:
            cpf_input = page.get_by_label("CPF", exact=False).first
            if not cpf_input.is_visible(timeout=1500):
                cpf_input = None
        except Exception:
            cpf_input = None
    if not cpf_input:
        return "Página de relatório detalhado não encontrou campo CPF."

    # Limpa e preenche para evitar filtro parcial / valor residual.
    try:
        cpf_input.click(timeout=2000)
        cpf_input.fill("")
        page.wait_for_timeout(200)
    except Exception:
        pass
    cpf_input.fill(cpf_limpo)
    page.wait_for_timeout(400)

    clicked = False
    for ctx in [page, *page.frames]:
        try:
            btn = ctx.locator(SEL["btn_filtrar"]).first
            if btn.is_visible(timeout=1500):
                btn.click()
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        page.keyboard.press("Enter")

    # Aguarda a grade recarregar (evita ler lista geral / resultados de outro CPF).
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    return None


def _parse_tabela(page: Page, cpf_consultado: str = "") -> Dict[str, Any]:
    """
    Lê a grade do relatório detalhado.

    Se ``cpf_consultado`` for informado, ignora linhas de outros CPF/CNPJ —
    evita falso positivo quando o filtro do GED ainda não aplicou e a tela
    mostra a listagem geral (ex.: Doc. Apto de outro cliente).
    """
    resultado: Dict[str, Any] = {
        "aprovada": False,
        "data_mais_recente_apta": None,
        "registros": [],
    }
    table = None
    for ctx in [page, *page.frames]:
        try:
            loc = ctx.locator(SEL["tabela"]).first
            if loc.is_visible(timeout=2000):
                table = loc
                break
        except Exception:
            continue
    if not table:
        # Sem tabela = nenhum registro (consulta ok)
        return resultado

    cpf_alvo = _normalizar_cpf(cpf_consultado)
    registros: List[Dict[str, str]] = []
    registros_outros = 0
    datas_aptas: List[str] = []
    rows = table.locator("tbody tr")
    n = rows.count()
    for i in range(n):
        tr = rows.nth(i)
        cells = tr.locator("td")
        n_cells = cells.count()
        if n_cells < 12:
            continue

        def cell_text(idx: int) -> str:
            cell = cells.nth(idx)
            try:
                div = cell.locator("div").first
                if div.count():
                    return (div.inner_text() or "").strip()
            except Exception:
                pass
            return (cell.inner_text() or "").strip()

        textos = [cell_text(j) for j in range(n_cells)]
        registro = {
            "protocolo": textos[0] if len(textos) > 0 else "",
            "cpf_cnpj": textos[1] if len(textos) > 1 else "",
            "n_linha": textos[2] if len(textos) > 2 else "",
            "linha_provisoria": textos[3] if len(textos) > 3 else "",
            "data_envio": textos[4] if len(textos) > 4 else "",
            "data_conferencia": textos[5] if len(textos) > 5 else "",
            "regional": textos[6] if len(textos) > 6 else "",
            "cod_pdv": textos[7] if len(textos) > 7 else "",
            "login": textos[8] if len(textos) > 8 else "",
            "tipo_servico": textos[9] if len(textos) > 9 else "",
            "nome_fantasia": textos[10] if len(textos) > 10 else "",
            "resultado_analise": textos[11] if len(textos) > 11 else "",
            "versao_app": textos[12] if len(textos) > 12 else "",
        }

        if cpf_alvo and registro["cpf_cnpj"]:
            if not _cpf_digitos_iguais(registro["cpf_cnpj"], cpf_alvo):
                registros_outros += 1
                continue
        elif cpf_alvo and not registro["cpf_cnpj"]:
            # Linha sem CPF na coluna — não confiar para aprovação.
            registros_outros += 1
            continue

        registros.append(registro)
        if STATUS_APTO_VENDA in registro["resultado_analise"] and registro["data_envio"]:
            datas_aptas.append(registro["data_envio"])

    if registros_outros:
        logger.warning(
            "[BrPronto] Grade com %s linha(s) de outro CPF/sem CPF (filtradas). "
            "cpf_consultado=%s linhas_do_cpf=%s — possível filtro GED incompleto.",
            registros_outros,
            cpf_alvo or "(vazio)",
            len(registros),
        )

    resultado["registros"] = registros

    def parse_data(s: str) -> Optional[Tuple[int, int, int, int, int, int]]:
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", s.strip())
        if m:
            return (
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1)),
                int(m.group(4)),
                int(m.group(5)),
                int(m.group(6)),
            )
        return None

    datas_parseadas = [(parse_data(d), d) for d in datas_aptas if parse_data(d)]
    datas_parseadas.sort(key=lambda x: x[0], reverse=True)
    if datas_parseadas:
        resultado["aprovada"] = True
        resultado["data_mais_recente_apta"] = datas_parseadas[0][1]
    return resultado


def _capturar_screenshot_b64(page: Page) -> Optional[str]:
    """
    Captura o trecho do relatório com a tabela de resultado (rodapé da página).

    A grade fica abaixo dos filtros; um print do viewport inicial corta a tabela.
    Prioriza screenshot do elemento da tabela; senão rola até o final e captura a tela.
    """
    try:
        # 1) Preferência: print direto da tabela de resultado.
        for ctx in [page, *page.frames]:
            try:
                tabela = ctx.locator(SEL["tabela"]).first
                if tabela.count() and tabela.is_visible(timeout=1500):
                    tabela.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(400)
                    png_bytes = tabela.screenshot(type="png")
                    if png_bytes:
                        return base64.b64encode(png_bytes).decode("ascii")
            except Exception:
                continue

        # 2) Rola até o título "Resultado da Consulta" (ou fim da página).
        scrolled = False
        for ctx in [page, *page.frames]:
            try:
                titulo = ctx.get_by_text("Resultado da Consulta", exact=False).first
                if titulo.count() and titulo.is_visible(timeout=1500):
                    titulo.scroll_into_view_if_needed(timeout=3000)
                    scrolled = True
                    break
            except Exception:
                continue
        if not scrolled:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
        page.wait_for_timeout(500)

        png_bytes = page.screenshot(type="png", full_page=False)
        if not png_bytes:
            return None
        return base64.b64encode(png_bytes).decode("ascii")
    except Exception as e:
        logger.warning("[BrPronto] Falha ao capturar screenshot: %s", e)
        return None


def consultar_biometria_brpronto(
    login: str,
    senha: str,
    cpf: str,
    dominio: Optional[str] = None,
    headless: bool = True,
    timeout_ms: int = 60000,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Consulta o Br Pronto PDV por CPF e retorna se existe biometria aprovada e a lista de registros.

    Returns:
        Tuple (sucesso, mensagem_erro, resultado).
        Em caso de falha: (False, mensagem, {}).
        Em sucesso, resultado pode incluir ``screenshot_b64`` (PNG da tela do relatório).
    """
    if not HAS_PLAYWRIGHT:
        return False, "Playwright não está instalado.", {}

    cpf_limpo = _normalizar_cpf(cpf)
    if len(cpf_limpo) != 11:
        return False, "CPF deve ter 11 dígitos.", {}

    if not login or not senha:
        return False, "Login e senha Br Pronto são obrigatórios. Configure no cadastro do usuário.", {}

    resultado: Dict[str, Any] = {
        "aprovada": False,
        "data_mais_recente_apta": None,
        "registros": [],
        "screenshot_b64": None,
    }
    logout_info = ""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                err = _login_brpronto(page, login, senha, dominio, timeout_ms)
                if err:
                    return False, err, {}

                err = _abrir_relatorio_detalhado(page)
                if err:
                    return False, err, {}

                err = _preencher_cpf_e_filtrar(page, cpf_limpo)
                if err:
                    return False, err, {}

                resultado = _parse_tabela(page, cpf_consultado=cpf_limpo)
                # Print da tela do relatório (com ou sem registros) para anexar no WhatsApp.
                resultado["screenshot_b64"] = _capturar_screenshot_b64(page)
                return True, None, resultado
            finally:
                try:
                    logout_info = _ensure_logout(page)
                    logger.info("[BrPronto] Logoff: %s (login=%s)", logout_info, login)
                except Exception as e_logout:
                    logger.warning("[BrPronto] Falha no logoff de %s: %s", login, e_logout)
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        logger.exception("[BrPronto] Erro ao consultar biometria: %s", e)
        return False, str(e), {}
