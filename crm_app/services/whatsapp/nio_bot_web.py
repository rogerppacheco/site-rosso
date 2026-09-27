"""Automação WhatsApp Web — bot oficial Nio (21 3605-1000) para reagendamento."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from playwright.sync_api import BrowserContext, Locator, Page, sync_playwright

logger = logging.getLogger(__name__)

NIO_TITLE_HINTS = ("3605-1000", "3605 1000", "36051000", "nio")

SUCESSO_AGENDADO_RE = re.compile(
    r"Tudo certo,\s*(?P<nome>[^.]+)\.\s*"
    r".*?Sua visita está agendada pro endereço\s+(?P<endereco>.+?),\s*"
    r"(?P<data>\d{2}/\d{2}/\d{4}),\s*no período das\s+"
    r"(?P<inicio>\d{2}:\d{2})\s*às\s*(?P<fim>\d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ResultadoReagendamentoNio:
    ok: bool
    status: str
    mensagem: str
    dados: dict | None = None


def _profile_dir() -> str:
    return str(getattr(settings, 'WHATSAPP_NIO_PROFILE_DIR', ''))


def _state_path() -> str:
    return str(getattr(settings, 'WHATSAPP_NIO_STATE_PATH', ''))


def _headless() -> bool:
    return bool(getattr(settings, 'WHATSAPP_NIO_HEADLESS', True))


def _bloco_recente(texto: str, linhas: int = 10) -> str:
    blocos = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    blocos = [ln for ln in blocos if ln.lower() != "digite uma mensagem"]
    return "\n".join(blocos[-linhas:])


def _ultimas_linhas(texto: str, n: int = 6) -> str:
    linhas = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    return "\n".join(linhas[-n:]).lower()


def _pede_cpf(recente: str) -> bool:
    """Detecta pedido de CPF nas últimas linhas do bot."""
    ultimas = _ultimas_linhas(recente, 2)
    return any(
        x in ultimas
        for x in (
            "digite seu cpf",
            "digite seu cpf ou cnpj",
            "digite o cpf",
            "digite o cpf ou cnpj",
            "cpf ou cnpj",
            "apenas o cpf",
            "preciso que você digite o cpf",
            "preciso que voce digite o cpf",
            "cpf ou cnpj da pessoa titular",
            "pessoa titular",
            "pessoa responsável",
        )
    )


def _pede_cpf_na_tela(page: Page) -> bool:
    return _pede_cpf(_texto_contexto_bot(page, 6))


def _bolhas_recebidas(page: Page) -> Locator:
    """Bolhas recebidas (bot Nio) — message-in é mais confiável que data-pre-plain-text."""
    loc = page.locator("#main div.message-in")
    if loc.count() > 0:
        return loc
    return page.locator("#main [data-pre-plain-text]")


def _direcao_mensagem(bubble: Locator) -> str:
    """incoming = bot Nio; outgoing = operador/automação."""
    try:
        html_class = bubble.get_attribute("class") or ""
        if "message-in" in html_class:
            return "in"
        if "message-out" in html_class:
            return "out"
    except Exception:
        pass
    pre = ""
    try:
        pre = bubble.get_attribute("data-pre-plain-text") or ""
    except Exception:
        pass
    if "+55 21 3605-1000" in pre or "21 3605-1000" in pre:
        return "in"
    if pre.startswith("[") and "21 3605" not in pre:
        return "out"
    return "in"


def _ultima_bolha_bot(page: Page) -> Locator | None:
    recebidas = _bolhas_recebidas(page)
    try:
        if recebidas.count() > 0:
            return recebidas.last
    except Exception:
        pass
    bubbles = _bubbles_mensagens(page)
    for i in range(bubbles.count() - 1, -1, -1):
        bolha = bubbles.nth(i)
        if _direcao_mensagem(bolha) == "in":
            return bolha
    return None


def _texto_ultimas_mensagens_bot(page: Page, n: int = 3) -> str:
    """Últimas N mensagens recebidas do bot (ordem cronológica)."""
    partes: list[str] = []
    recebidas = _bolhas_recebidas(page)
    try:
        count = recebidas.count()
        for i in range(max(0, count - n), count):
            texto = (recebidas.nth(i).inner_text() or "").strip()
            if texto:
                partes.append(texto)
        if partes:
            return "\n".join(partes)
    except Exception:
        pass
    bubbles = _bubbles_mensagens(page)
    vistas = 0
    temp: list[str] = []
    for i in range(bubbles.count() - 1, -1, -1):
        bolha = bubbles.nth(i)
        if _direcao_mensagem(bolha) != "in":
            continue
        try:
            t = (bolha.inner_text() or "").strip()
            if t:
                temp.insert(0, t)
        except Exception:
            pass
        vistas += 1
        if vistas >= n:
            break
    return "\n".join(temp)


def _scroll_chat_fim(page: Page) -> None:
    """Garante que bolhas recentes estejam renderizadas."""
    try:
        alvos = page.locator("#main [data-testid='conversation-panel-messages'], #main")
        if alvos.count() > 0:
            alvos.last.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.wait_for_timeout(600)
    except Exception:
        pass


def _linha_parece_usuario(linha: str) -> bool:
    low = linha.strip().lower()
    if not low:
        return True
    if low in ("oi", "sair", "sim", "não", "nao"):
        return True
    if re.fullmatch(r"\d{11}", linha.strip()):
        return True
    if RE_HORA_BOTAO.match(linha.strip()):
        return True
    if low == "digite uma mensagem":
        return True
    return False


def _texto_contexto_bot(page: Page, linhas: int = 6) -> str:
    """Texto recente do bot — message-in, bolhas ou painel filtrado."""
    bot = _texto_ultimas_mensagens_bot(page, 3)
    if bot.strip():
        return bot

    recente = _texto_mensagens_recentes(page, 10)
    filtradas = [ln.strip() for ln in recente.splitlines() if ln.strip() and not _linha_parece_usuario(ln)]
    if filtradas:
        return "\n".join(filtradas[-linhas:])

    painel = _bloco_recente(_panel_text(page), linhas + 4)
    filtradas_p = [ln.strip() for ln in painel.splitlines() if ln.strip() and not _linha_parece_usuario(ln)]
    return "\n".join(filtradas_p[-linhas:])


def _rotulo_botao_valido(texto: str) -> bool:
    t = (texto or "").strip()
    if not t or len(t) > 60:
        return False
    if RE_HORA_BOTAO.match(t):
        return False
    return True


def _texto_ultima_mensagem(page: Page) -> str:
    """Texto da última bolha recebida do bot (estado atual)."""
    ctx = _texto_contexto_bot(page, 4)
    if ctx.strip():
        linhas = [ln for ln in ctx.splitlines() if ln.strip()]
        if linhas:
            return linhas[-1]
    bot = _ultima_bolha_bot(page)
    if bot is not None:
        try:
            return (bot.inner_text() or "").strip()
        except Exception:
            pass
    bubbles = _bubbles_mensagens(page)
    if bubbles.count() == 0:
        return _bloco_recente(_panel_text(page), 6)
    try:
        return (bubbles.last.inner_text() or "").strip()
    except Exception:
        return _bloco_recente(_panel_text(page), 6)


def _pede_menu_produtos(recente: str) -> bool:
    """Menu inicial: 'Para qual desses produtos você deseja atendimento?'"""
    ultimas = _ultimas_linhas(recente, 8)
    return "para qual desses produtos" in ultimas


def _pede_menu_produtos_na_tela(page: Page, botoes_visiveis: list[str] | None = None) -> bool:
    """Menu de produtos — texto do bot ou botões conhecidos visíveis."""
    if _lista_instalacao_visivel(page):
        return False
    ultimas_bot = _texto_contexto_bot(page, 4).lower()
    bl = {b.lower() for b in (_botoes_ultima_bolha(page) + (botoes_visiveis or []))}
    if ("sim" in bl and ("não" in bl or "nao" in bl)) and any(
        x in ultimas_bot for x in ("encontrei o cpf", "é pra esse", "e pra esse")
    ):
        return False
    if "para qual desses produtos" in ultimas_bot or "escolha um produto da lista" in ultimas_bot:
        return True
    return "escolha um produto da lista" in bl or "produtos contratados" in bl


def _menu_produtos_ativo(page: Page) -> bool:
    if _lista_instalacao_visivel(page):
        return False
    return _pede_menu_produtos_na_tela(page)


def _pede_produto(recente: str, botoes: list[str] | None = None) -> bool:
    """Compat: menu de produtos ou lista de instalação já aberta."""
    return _pede_menu_produtos(recente) or _pede_lista_instalacao(recente)


RE_CEP_MASCARADO_NIO = re.compile(r"CEP\s*\*+-(\d{3})", re.IGNORECASE)
RE_INTERNET_INSTALACAO = re.compile(r"internet em instala", re.IGNORECASE)
RE_CEP_SUFIXO_TEXTO = re.compile(r"\*+-(\d{3})", re.IGNORECASE)
RE_HORA_BOTAO = re.compile(r"^\d{1,2}:\d{2}$")


def sufixo_cep_pedido(cep: str | None) -> str:
    """Últimos 3 dígitos do CEP (ex.: 12345-678 → 678), para bater com ***-678 no bot."""
    digits = re.sub(r"\D", "", cep or "")
    return digits[-3:] if len(digits) >= 3 else ""


def _extrair_sufixos_cep_mascarados(texto: str) -> list[str]:
    sufixos = RE_CEP_MASCARADO_NIO.findall(texto or "")
    if sufixos:
        return sufixos
    return RE_CEP_SUFIXO_TEXTO.findall(texto or "")


def _texto_overlay_apenas(page: Page) -> str:
    """Texto só de overlays/modais (lista de produtos costuma abrir aqui)."""
    partes: list[str] = []
    for sel in (
        '[role="dialog"]',
        '[data-animate-modal-popup="true"]',
        '[data-testid="popup"]',
        '[data-testid="drawer-right"]',
    ):
        loc = page.locator(sel)
        try:
            if loc.count() == 0:
                continue
            texto = (loc.first.inner_text() or "").strip()
            if texto:
                partes.append(texto)
        except Exception:
            continue
    return "\n".join(partes)


def _bubbles_mensagens(page: Page) -> Locator:
    bubbles = page.locator("#main [data-pre-plain-text]")
    if bubbles.count() == 0:
        bubbles = page.locator("#main [data-testid='msg-container']")
    return bubbles


def _texto_mensagens_recentes(page: Page, n: int = 8) -> str:
    """Só as últimas bolhas do chat — evita 'Internet em instalação' no histórico antigo."""
    bubbles = _bubbles_mensagens(page)
    count = bubbles.count()
    if count == 0:
        return _bloco_recente(_panel_text(page), n)
    start = max(0, count - n)
    partes: list[str] = []
    for i in range(start, count):
        try:
            texto = (bubbles.nth(i).inner_text() or "").strip()
            if texto:
                partes.append(texto)
        except Exception:
            continue
    return "\n".join(partes)


def _texto_overlay_e_chat(page: Page) -> str:
    """Texto visível no chat + overlays/modais (lista de produtos)."""
    overlay = _texto_overlay_apenas(page)
    recente = _texto_mensagens_recentes(page, 10)
    if overlay and recente:
        return f"{overlay}\n{recente}"
    return overlay or recente or _panel_text(page)


def _texto_tem_lista_instalacao(texto: str) -> bool:
    return bool(RE_INTERNET_INSTALACAO.search(texto or "")) and bool(
        _extrair_sufixos_cep_mascarados(texto or "")
    )


def _pede_lista_instalacao(recente: str) -> bool:
    return _texto_tem_lista_instalacao(recente)


def _botoes_ultima_bolha(page: Page) -> list[str]:
    """Quick replies só da última bolha recebida do bot."""
    labels: list[str] = []
    try:
        root = _ultima_bolha_bot(page)
        if root is None:
            return labels
        for btn in root.locator("button, [role='button']").all()[:12]:
            t = (btn.inner_text() or "").strip()
            if _rotulo_botao_valido(t):
                labels.append(t)
    except Exception:
        pass
    return labels


def _texto_lista_produto_ativa(page: Page) -> str:
    """Texto da lista interativa aberta — overlay ou só a última bolha do bot."""
    overlay = _texto_overlay_apenas(page)
    if overlay and _texto_tem_lista_instalacao(overlay):
        return overlay
    if _produto_selecionado_com_sucesso(page):
        return ""
    try:
        recebidas = _bolhas_recebidas(page)
        if recebidas.count() > 0:
            texto = (recebidas.last.inner_text() or "").strip()
            if _texto_tem_lista_instalacao(texto):
                return texto
    except Exception:
        pass
    return ""


def _lista_instalacao_visivel(page: Page) -> bool:
    return bool(_texto_lista_produto_ativa(page))


def _produto_selecionado_com_sucesso(page: Page) -> bool:
    """Menu pós-produto (Reagendar etc.) — sem chamar _lista_instalacao_visivel (evita recursão)."""
    bl = _botoes_ultima_bolha(page)
    if any(b in bl for b in ("Reagendar", "Agendar", "Confirmar data")):
        return True
    try:
        recebidas = _bolhas_recebidas(page)
        if recebidas.count() > 0:
            ultima = (recebidas.last.inner_text() or "").lower()
        else:
            ultima = _texto_mensagens_recentes(page, 6).lower()
    except Exception:
        ultima = _texto_mensagens_recentes(page, 6).lower()
    return any(
        x in ultima
        for x in (
            "o que você gostaria de fazer",
            "o que voce gostaria de fazer",
            "boa notícia",
            "boa noticia",
            "já pode reagendar",
            "ja pode reagendar",
            "reagendar a instalação",
            "reagendar a instalacao",
            "confirmar data",
            "primeira data disponível",
            "primeira data disponivel",
        )
    )


def _aguardar_lista_instalacao(page: Page, timeout_sec: int = 20) -> str:
    """Espera 'Internet em instalação' + CEP mascarado (chat ou overlay)."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        page.wait_for_timeout(700)
        if _lista_instalacao_visivel(page):
            return _texto_overlay_e_chat(page)
    return ""


def _abrir_lista_produtos(page: Page) -> str | None:
    """Abre o picker: prioriza 'Escolha um produto da lista' (lista com radio)."""
    if _lista_instalacao_visivel(page):
        return "lista_ja_aberta"

    clicado = _click_botao_prioridade(page, ("Escolha um produto da lista",))
    if not clicado:
        clicado = _click_texto_chat(page, ("Escolha um produto da lista",))
    if not clicado:
        try:
            bubbles = _bubbles_mensagens(page)
            if bubbles.count() > 0:
                alvo = bubbles.last.get_by_text("Escolha um produto da lista", exact=True)
                if alvo.count() > 0 and alvo.last.is_visible():
                    alvo.last.click(timeout=4000)
                    clicado = "Escolha um produto da lista"
        except Exception:
            pass

    if clicado:
        page.wait_for_timeout(2000)
        return clicado

    clicado = _click_botao_prioridade(page, ("Produtos contratados",))
    if clicado:
        page.wait_for_timeout(1800)
        if _lista_instalacao_visivel(page):
            return clicado
        sub = _click_botao_prioridade(page, ("Escolha um produto da lista",))
        if sub:
            page.wait_for_timeout(2000)
            return sub
    return None


def _clicar_botao_enviar_whatsapp(page: Page) -> bool:
    """Clica o ícone de enviar do compositor (após selecionar item da lista interativa)."""
    seletores = (
        '[data-testid="wds-ic-send-filled"]',
        '[data-icon="wds-ic-send-filled"]',
        'span[data-testid="send"]',
        '[data-testid="compose-btn-send"]',
        '#main footer button[aria-label*="Enviar" i]',
        '#main footer button[aria-label*="Send" i]',
    )
    for sel in seletores:
        loc = page.locator(sel)
        try:
            for i in range(loc.count() - 1, -1, -1):
                btn = loc.nth(i)
                if not btn.is_visible():
                    continue
                pai = btn.locator("xpath=ancestor::button[1]")
                alvo = pai if pai.count() > 0 else btn
                alvo.click(timeout=4000)
                page.wait_for_timeout(1200)
                return True
        except Exception:
            continue
    try:
        footer = page.locator("#main footer")
        if footer.count() > 0:
            btn = footer.first.locator("button").last
            if btn.is_visible():
                btn.click(timeout=4000)
                page.wait_for_timeout(1200)
                return True
    except Exception:
        pass
    try:
        compose = page.locator("#main footer div[contenteditable='true']").first
        if compose.count() > 0 and compose.is_visible():
            compose.click(timeout=3000)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            return True
    except Exception:
        pass
    return False


def _confirmar_selecao_lista(page: Page) -> str | None:
    """Confirma seleção na lista interativa — no WhatsApp Web isso é o botão enviar (▶)."""
    if _clicar_botao_enviar_whatsapp(page):
        return "send-filled"

    for label in ("Enviar", "Confirmar", "OK", "Continuar", "Selecionar"):
        for scope in (
            page.locator('[role="dialog"]'),
            page.locator('[data-animate-modal-popup="true"]'),
            page.locator("#main"),
        ):
            try:
                if scope.count() == 0:
                    continue
                btn = scope.first.get_by_role("button", name=label)
                if btn.count() > 0 and btn.last.is_visible():
                    btn.last.click(timeout=3000)
                    return label
                txt = scope.first.get_by_text(label, exact=True)
                if txt.count() > 0 and txt.last.is_visible():
                    txt.last.click(timeout=3000)
                    return label
            except Exception:
                continue
    return _click_botao_prioridade(page, ("Enviar", "Confirmar", "OK", "Continuar"))


def _radio_internet_selecionado(page: Page, sufixo: str) -> bool:
    padrao_cep = re.compile(rf"\*+\s*-\s*{re.escape(sufixo)}\b", re.IGNORECASE)
    try:
        marcadores = page.locator('svg title').filter(
            has_text=re.compile(r"radio-button-checked", re.IGNORECASE)
        )
        for i in range(min(marcadores.count(), 12)):
            bloco = marcadores.nth(i).locator("xpath=ancestor::div[3]")
            texto = (bloco.inner_text() or "").strip()
            if RE_INTERNET_INSTALACAO.search(texto) and padrao_cep.search(texto):
                return True
    except Exception:
        pass
    return False


def _clicar_produto_inline_ultima_bolha(page: Page, sufixo: str) -> bool:
    """Clica a linha 'Internet em instalação' + CEP na última bolha recebida do bot."""
    bolha = _ultima_bolha_bot(page)
    if bolha is None:
        return False
    padrao_cep = re.compile(rf"\*+\s*-\s*{re.escape(sufixo)}\b", re.IGNORECASE)
    try:
        for sel in ("[role='button']", "button", "[tabindex='0']", "li", "div"):
            loc = bolha.locator(sel)
            for i in range(min(loc.count(), 20)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    texto = (el.inner_text() or "").strip()
                    if not RE_INTERNET_INSTALACAO.search(texto) or not padrao_cep.search(texto):
                        continue
                    if len(texto) > 350:
                        continue
                    el.click(timeout=5000)
                    page.wait_for_timeout(1200)
                    return True
                except Exception:
                    continue
        cep_loc = bolha.get_by_text(re.compile(rf"\*+\s*-\s*{re.escape(sufixo)}", re.IGNORECASE))
        if cep_loc.count() > 0:
            alvo = cep_loc.last
            try:
                alvo.click(timeout=5000)
            except Exception:
                alvo.click(timeout=5000, force=True)
            page.wait_for_timeout(1200)
            return True
    except Exception:
        pass
    return _clicar_internet_instalacao_js(page, sufixo)


def _clicar_internet_instalacao_js(page: Page, sufixo: str) -> bool:
    """Fallback JS: clica a linha clicável com Internet em instalação + CEP ***-XYZ."""
    try:
        return bool(
            page.evaluate(
                """(sufixo) => {
                    const reInst = /internet em instala/i;
                    const reCep = new RegExp(`\\\\*+-${sufixo}\\\\b`, 'i');
                    const roots = [
                        ...document.querySelectorAll('[role="dialog"], [data-animate-modal-popup="true"], #main')
                    ];
                    for (const root of roots) {
                        const nodes = root.querySelectorAll('div, li, label, span, [role="listitem"], [role="radio"]');
                        let best = null;
                        let bestLen = 99999;
                        for (const el of nodes) {
                            const t = (el.innerText || '').trim();
                            if (!t || t.length > 350 || !reInst.test(t) || !reCep.test(t)) continue;
                            if (t.length < bestLen) { best = el; bestLen = t.length; }
                        }
                        if (best) { best.click(); return true; }
                    }
                    return false;
                }""",
                sufixo,
            )
        )
    except Exception:
        return False


def _click_texto_chat(page: Page, textos: tuple[str, ...]) -> str | None:
    """Clica o último elemento visível no chat que contém o texto (quick replies)."""
    footer_y = _footer_y(page)
    for texto_alvo in textos:
        loc = page.locator("#main").get_by_text(texto_alvo, exact=True)
        for i in range(loc.count() - 1, -1, -1):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                box = el.bounding_box()
                if not box or box["y"] >= footer_y - 8:
                    continue
                el.click(timeout=4000)
                return texto_alvo
            except Exception:
                continue
    return None


def _scopes_lista_produto(page: Page) -> list[Locator]:
    scopes: list[Locator] = []
    for sel in (
        '[role="dialog"]',
        '[data-animate-modal-popup="true"]',
        '[data-testid="popup"]',
        '[data-testid="drawer-right"]',
    ):
        loc = page.locator(sel)
        if loc.count() > 0:
            scopes.append(loc.first)
    bubbles = _bubbles_mensagens(page)
    count = bubbles.count()
    for i in range(max(0, count - 4), count):
        scopes.append(bubbles.nth(i))
    return scopes


def _clicar_item_internet_por_cep(page: Page, sufixo: str) -> bool:
    """Clica o item da lista (radio) com Internet em instalação e CEP ***-XYZ."""
    padrao_internet = re.compile(r"internet em instala", re.IGNORECASE)
    padrao_cep = re.compile(rf"\*+\s*-\s*{re.escape(sufixo)}\b", re.IGNORECASE)

    for scope in _scopes_lista_produto(page):
        try:
            if scope.count() == 0:
                continue
            root = scope

            # 1) Texto exato visível (lista inline no chat)
            for texto_alvo in (f"Internet em instalação", f"Internet em instalacao"):
                try:
                    loc = root.get_by_text(texto_alvo, exact=False)
                    for i in range(min(loc.count(), 8) - 1, -1, -1):
                        el = loc.nth(i)
                        if not el.is_visible():
                            continue
                        bloco = (el.locator("xpath=ancestor::div[1]").inner_text() or el.inner_text() or "")
                        if padrao_cep.search(bloco):
                            el.click(timeout=5000)
                            page.wait_for_timeout(900)
                            return True
                except Exception:
                    continue

            linhas = root.locator(
                "div, li, label, span, [role='listitem'], [role='radio'], [role='button']"
            ).filter(has_text=padrao_internet)
            melhor: tuple[int, Locator] | None = None
            for i in range(min(linhas.count(), 25)):
                el = linhas.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    texto = (el.inner_text() or "").strip()
                    if not padrao_cep.search(texto):
                        continue
                    tamanho = len(texto)
                    if tamanho > 400:
                        continue
                    if melhor is None or tamanho < melhor[0]:
                        melhor = (tamanho, el)
                except Exception:
                    continue
            if melhor:
                el = melhor[1]
                try:
                    el.click(timeout=5000)
                except Exception:
                    el.click(timeout=5000, force=True)
                page.wait_for_timeout(900)
                return True

            radios = root.locator('[role="radio"], [aria-checked], svg title')
            for i in range(min(radios.count(), 20)):
                radio = radios.nth(i)
                try:
                    if not radio.is_visible():
                        continue
                    bloco_txt = (radio.locator("xpath=ancestor::div[2]").inner_text() or "")
                    if padrao_internet.search(bloco_txt) and padrao_cep.search(bloco_txt):
                        radio.click(timeout=5000)
                        page.wait_for_timeout(900)
                        return True
                except Exception:
                    continue
        except Exception:
            continue

    if _clicar_internet_instalacao_js(page, sufixo):
        page.wait_for_timeout(900)
        return True
    return False


def _selecionar_internet_instalacao_por_cep(
    page: Page, *, cep_sufixo_esperado: str
) -> tuple[bool, str]:
    """
    Seleciona o item 'Internet em instalação' cujo CEP mascarado (***-XYZ)
    coincide com o final do CEP do pedido na esteira.
    """
    sufixo = (cep_sufixo_esperado or "")[-3:]
    if len(sufixo) != 3:
        return False, "Pedido sem CEP válido para validar produto no bot."

    if not _lista_instalacao_visivel(page):
        return False, "Lista 'Internet em instalação' não visível nas mensagens recentes."

    texto = _texto_lista_produto_ativa(page)
    achados = _extrair_sufixos_cep_mascarados(texto)
    if sufixo not in achados:
        opcoes = ", ".join(f"***-{s}" for s in achados) if achados else "nenhuma"
        return False, f"CEP ***-{sufixo} não encontrado na lista ativa. Opções: {opcoes}"

    clicou = False
    for _ in range(3):
        if _radio_internet_selecionado(page, sufixo):
            clicou = True
            break
        if _clicar_item_internet_por_cep(page, sufixo):
            clicou = True
        page.wait_for_timeout(700)
        if _radio_internet_selecionado(page, sufixo):
            break

    if not clicou:
        return False, f"Não foi possível clicar em Internet em instalação (CEP ***-{sufixo})."

    page.wait_for_timeout(800)
    confirmado: str | None = None
    if _clicar_botao_enviar_whatsapp(page):
        confirmado = "send-filled"
    else:
        confirmado = _confirmar_selecao_lista(page)

    page.wait_for_timeout(2500)

    if confirmado:
        if _produto_selecionado_com_sucesso(page):
            return True, f"Produto selecionado e enviado via {confirmado}."
        if not _lista_instalacao_visivel(page):
            return True, f"Produto enviado via {confirmado} (lista fechou)."

    if _radio_internet_selecionado(page, sufixo) or clicou:
        return True, f"Radio Internet em instalação (CEP ***-{sufixo}) marcado — aguardando envio."

    return False, "Clique no produto não avançou o fluxo."


def _selecionar_produto_nio(page: Page, *, cep_sufixo_esperado: str = "") -> tuple[bool, str | None]:
    """Abre lista de produtos e seleciona Internet em instalação validando CEP."""
    if _produto_selecionado_com_sucesso(page):
        return True, "Produto já selecionado."

    sufixo = (cep_sufixo_esperado or "")[-3:]

    if _lista_instalacao_visivel(page):
        return _selecionar_internet_instalacao_por_cep(page, cep_sufixo_esperado=cep_sufixo_esperado)

    ctx = _texto_contexto_bot(page, 5).lower()
    if "para qual desses produtos" in ctx and len(sufixo) == 3:
        before = _panel_text(page)
        if _clicar_produto_inline_ultima_bolha(page, sufixo):
            _wait_new(page, before, 20)
            page.wait_for_timeout(1500)
            if _produto_selecionado_com_sucesso(page):
                return True, "Produto inline selecionado — menu de ações."
            ctx_pos = _texto_contexto_bot(page, 4).lower()
            if "ah, que pena" in ctx_pos or "ah, que pe" in ctx_pos:
                return False, "Bot recusou seleção inline do produto."
            if not _pede_menu_produtos_na_tela(page):
                return True, "Produto inline selecionado."
            return True, "Clique inline no produto — aguardando resposta."
        return False, f"Não clicou produto inline (CEP ***-{sufixo})."

    if not _pede_menu_produtos_na_tela(page):
        return False, "Menu de produtos não detectado."

    clicado = _abrir_lista_produtos(page)
    if not clicado:
        return False, "Não foi possível clicar em 'Escolha um produto da lista'."

    if not _aguardar_lista_instalacao(page, timeout_sec=22):
        return False, "Lista de produtos não abriu após clique (Internet em instalação não apareceu)."

    return _selecionar_internet_instalacao_por_cep(page, cep_sufixo_esperado=cep_sufixo_esperado)


def _tem_prompt_cpf(texto: str) -> bool:
    """Só considera prompt de CPF nas últimas linhas — evita botões antigos no histórico."""
    ultimas = _ultimas_linhas(texto, 6)
    return (
        "é pra esse que você quer atendimento" in ultimas
        or "e pra esse que voce quer atendimento" in ultimas
        or "quer continuar com o cpf" in ultimas
    )


def _sessao_cpf_encerrada(texto: str) -> bool:
    t = (texto or "").lower()
    return any(
        p in t
        for p in (
            "não me confirmou o cpf",
            "nao me confirmou o cpf",
            "não consigo achar o cadastro",
            "nao consigo achar o cadastro",
            "tente de novo mais tarde",
            "sistema de consulta não está muito legal",
            "sistema de consulta nao esta muito legal",
            "tente mais tarde",
        )
    )


def _parse_sucesso_agendado(texto: str) -> dict | None:
    m = SUCESSO_AGENDADO_RE.search(texto or "")
    if not m:
        return None
    data = m.group("data")
    if "invalid" in data.lower():
        return None
    return {
        "nome": m.group("nome").strip(),
        "endereco": re.sub(r"\s+", " ", m.group("endereco")).strip(),
        "data": data,
        "inicio": m.group("inicio"),
        "fim": m.group("fim"),
    }


def _classificar(texto: str) -> dict:
    t = (texto or "").lower()
    falha_sem_slot = any(
        p in t
        for p in (
            "não encontramos datas",
            "nao encontramos datas",
            "sem datas disponíveis",
            "sem datas disponiveis",
            "não há horários",
            "nao ha horarios",
        )
    )
    falha_consulta = any(
        p in t
        for p in (
            "sistema de consulta não está muito legal",
            "sistema de consulta nao esta muito legal",
            "tente mais tarde",
            "tente de novo mais tarde",
            "não consigo achar o cadastro",
            "nao consigo achar o cadastro",
        )
    )
    bug_data = "invalid date" in t
    sucesso_agendado = _parse_sucesso_agendado(texto)
    sucesso = bool(sucesso_agendado) and not falha_sem_slot and not bug_data and not falha_consulta
    if bug_data:
        sucesso = False
        sucesso_agendado = None
    return {
        "falha_sem_slot": falha_sem_slot,
        "falha_consulta": falha_consulta,
        "prompt_cpf": _tem_prompt_cpf(texto),
        "sessao_cpf_encerrada": _sessao_cpf_encerrada(texto),
        "bug_invalid_date": bug_data,
        "sucesso_agendado": sucesso_agendado,
        "sucesso_aparente": sucesso,
    }


def _panel_text(page: Page) -> str:
    for sel in (
        "#main",
        "[data-testid='conversation-panel-body']",
        "[data-testid='conversation-panel-messages']",
    ):
        loc = page.locator(sel)
        try:
            if loc.count() == 0:
                continue
            texto = (loc.last.inner_text() or "").strip()
            if texto:
                return texto
        except Exception:
            continue
    return ""


def _delta_texto(antes: str, agora: str) -> str:
    agora = agora or ""
    antes = antes or ""
    if agora.startswith(antes):
        return agora[len(antes):].strip()
    return agora[-900:].strip()


def _is_logged_in(page: Page) -> bool:
    markers = [
        "#pane-side",
        '[data-testid="chat-list"]',
        '[aria-label="Lista de conversas"]',
        'div[contenteditable="true"][data-tab="3"]',
    ]
    for sel in markers:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def _wait_login(page: Page, timeout_sec: int = 180) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _is_logged_in(page):
            return True
        page.wait_for_timeout(2000)
    return False


def _dismiss_overlays(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    for label in ("Continuar", "OK", "Fechar", "Agora não", "Entendi", "Não agora"):
        loc = page.get_by_role("button", name=label)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(300)
        except Exception:
            continue


def _chat_rows(page: Page) -> Locator:
    for sel in ('#pane-side [role="listitem"]', '[data-testid="cell-frame-container"]'):
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc
    return page.locator('#pane-side [role="listitem"]')


def _row_title(row: Locator) -> str:
    for sel in ('span[title]', '[data-testid="cell-frame-title"]', 'span[dir="auto"]'):
        el = row.locator(sel).first
        try:
            if el.count() == 0:
                continue
            title = el.get_attribute("title") or el.inner_text()
            if title and title.strip():
                return title.strip()
        except Exception:
            continue
    try:
        return (row.inner_text() or "").split("\n")[0].strip()
    except Exception:
        return ""


def _ensure_nio_conversation_open(page: Page) -> bool:
    hints = NIO_TITLE_HINTS
    _dismiss_overlays(page)
    rows = _chat_rows(page)
    for i in range(rows.count()):
        row = rows.nth(i)
        title = _row_title(row).lower()
        if any(h.lower() in title for h in hints):
            try:
                row.click(timeout=8000)
            except Exception:
                row.click(timeout=5000, force=True)
            page.wait_for_timeout(1500)
            return True
    return False


def _send_text(page: Page, text: str) -> bool:
    compose_selectors = [
        'div[contenteditable="true"][data-tab="10"]',
        'div[contenteditable="true"][aria-label*="mensagem" i]',
        '[data-testid="conversation-compose-box-input"]',
        '#main footer div[contenteditable="true"]',
    ]
    for sel in compose_selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() == 0:
                continue
            loc.click(timeout=4000)
            page.wait_for_timeout(200)
            loc.fill("")
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(text, delay=35)
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3500)
            return True
        except Exception:
            continue
    return False


def _footer_y(page: Page) -> float:
    try:
        box = page.locator("#main footer").first.bounding_box()
        if box:
            return float(box["y"])
    except Exception:
        pass
    return 10_000.0


def _botoes_visiveis_inferiores(page: Page) -> list[tuple[str, Locator, float]]:
    footer_y = _footer_y(page)
    achados: list[tuple[str, Locator, float]] = []
    loc = page.locator("#main button, #main [role='button']")
    for i in range(loc.count()):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if not box or box["y"] < 80 or box["y"] >= footer_y - 8:
                continue
            t = (el.inner_text() or "").strip()
            if not t or len(t) > 60 or "\n" in t:
                continue
            achados.append((t, el, float(box["y"])))
        except Exception:
            continue
    achados.sort(key=lambda x: x[2], reverse=True)
    return achados


def _visible_buttons(page: Page) -> list[str]:
    labels: list[str] = []
    for t, _el, _y in _botoes_visiveis_inferiores(page):
        if t.lower() not in {x.lower() for x in labels}:
            labels.append(t)
    return labels


def _click_botao_prioridade(page: Page, labels: tuple[str, ...]) -> str | None:
    """Clica o botão mais novo, respeitando a ordem de preferência em labels."""
    for label in labels:
        clicado = _click_botao_mais_novo(page, (label,))
        if clicado:
            return clicado
    return None


def _click_botao_mais_novo(page: Page, labels: tuple[str, ...]) -> str | None:
    wanted = {x.strip().lower() for x in labels}
    for texto, el, _y in _botoes_visiveis_inferiores(page):
        if texto.strip().lower() in wanted:
            try:
                el.click(timeout=4000)
                return texto
            except Exception:
                continue
    return None


def _wait_new(page: Page, before: str, timeout_sec: int = 28) -> str:
    deadline = time.time() + timeout_sec
    last = before or ""
    last_change = None
    while time.time() < deadline:
        page.wait_for_timeout(900)
        now = _panel_text(page)
        if now != last:
            last = now
            last_change = time.time()
        elif last_change is not None and (time.time() - last_change) >= 5:
            if len(now) > len(before) + 8:
                return now
    return _panel_text(page)


def _encerrar_com_sair(page: Page) -> None:
    before = _panel_text(page)
    _send_text(page, "sair")
    deadline = time.time() + 25
    texto = before
    while time.time() < deadline:
        texto = _wait_new(page, before, 8)
        if "até mais" in _bloco_recente(texto).lower() or "ate mais" in _bloco_recente(texto).lower():
            return
        before = texto


def _limpar_sessao_nio(page: Page) -> str:
    """Encerra sessão anterior (sair → Até mais) e reinicia com oi."""
    texto = ""
    for _ in range(2):
        _encerrar_com_sair(page)
        page.wait_for_timeout(2000)
        before = _panel_text(page)
        _send_text(page, "oi")
        texto = _wait_new(page, before, 35)
        deadline = time.time() + 22
        while time.time() < deadline:
            ult = _texto_ultima_mensagem(page).lower()
            if any(
                x in ult
                for x in (
                    "não me confirmou o cpf",
                    "nao me confirmou o cpf",
                    "não consigo achar o cadastro",
                    "nao consigo achar o cadastro",
                )
            ):
                break
            if any(
                x in ult
                for x in (
                    "olá",
                    "ola",
                    "como posso te ajudar",
                    "cpf",
                    "cnpj",
                    "cadastro",
                    "é pra esse",
                    "e pra esse",
                    "encontrei o cpf",
                )
            ):
                return texto
            page.wait_for_timeout(900)
    return texto


def executar_reagendamento_pedido(
    page: Page,
    *,
    cpf: str,
    cpf_mask_hint: str,
    nome_esperado: str,
) -> ResultadoReagendamentoNio:
    """Fluxo completo de reagendamento para um CPF no chat Nio já aberto."""
    _dismiss_overlays(page)
    if not _ensure_nio_conversation_open(page):
        return ResultadoReagendamentoNio(False, "erro", "Não foi possível abrir o chat Nio.")

    texto = _panel_text(page)
    delta = _bloco_recente(texto)

    for etapa in range(8):
        texto = _panel_text(page)
        recente = _bloco_recente(texto)
        delta = recente

        sucesso_id = _parse_sucesso_agendado(recente)
        if sucesso_id:
            _encerrar_com_sair(page)
            return ResultadoReagendamentoNio(True, "sucesso", "Agendado com sucesso.", sucesso_id)

        dlow = recente.lower()
        pede_cpf = (
            "digite seu cpf" in dlow
            or "cpf ou cnpj" in dlow
            or "digite o cpf" in dlow
            or "apenas o cpf" in dlow
        )
        if pede_cpf:
            before = texto
            _send_text(page, cpf)
            texto = _wait_new(page, before, 32)
            continue

        if _sessao_cpf_encerrada(recente) and not pede_cpf:
            before = texto
            _send_text(page, "oi")
            texto = _wait_new(page, before, 28)
            continue

        if _tem_prompt_cpf(recente):
            before = texto
            if cpf_mask_hint in recente:
                _click_botao_mais_novo(page, ("Sim",))
            else:
                _click_botao_mais_novo(page, ("Não", "Nao"))
            texto = _wait_new(page, before, 28)
            continue

        if "até mais" in dlow or "ate mais" in dlow:
            before = texto
            _send_text(page, "oi")
            texto = _wait_new(page, before, 28)
            continue
        break

    delta = _bloco_recente(_panel_text(page), 20)

    for _i in range(4):
        cls = _classificar(delta)
        sucesso = _parse_sucesso_agendado(delta)
        if sucesso:
            _encerrar_com_sair(page)
            return ResultadoReagendamentoNio(True, "sucesso", "Agendado com sucesso.", sucesso)

        if cls.get("falha_sem_slot"):
            _encerrar_com_sair(page)
            return ResultadoReagendamentoNio(False, "sem_slot", "Nio: sem datas disponíveis.")
        if cls.get("bug_invalid_date"):
            _encerrar_com_sair(page)
            return ResultadoReagendamentoNio(False, "erro", "Nio: Invalid Date.")
        if cls.get("falha_consulta") or cls.get("sessao_cpf_encerrada"):
            _encerrar_com_sair(page)
            status = "erro_cpf" if cls.get("sessao_cpf_encerrada") else "erro_consulta"
            return ResultadoReagendamentoNio(False, status, "Nio: consulta indisponível ou CPF não confirmado.")

        dlow = delta.lower()
        if "confirmar data" in dlow or "boa notícia" in dlow or "boa noticia" in dlow or "primeira data disponível" in dlow:
            before = texto
            _click_botao_mais_novo(page, ("Confirmar data",))
            texto = _wait_new(page, before, 35)
            delta = _delta_texto(before, texto)
            continue

        if "o que você gostaria de fazer" in dlow or "o que voce gostaria de fazer" in dlow:
            if _parse_sucesso_agendado(delta):
                continue
            before = texto
            _click_botao_mais_novo(page, ("Reagendar", "Agendar"))
            texto = _wait_new(page, before, 35)
            delta = _delta_texto(before, texto)
            continue
        break

    tail = delta[-400:] if delta else ""
    _encerrar_com_sair(page)
    logger.warning("[NIO REAGENDAMENTO] Fluxo inconcluso para %s: %s", nome_esperado, tail)
    return ResultadoReagendamentoNio(False, "erro", f"Fluxo inconcluso. {tail[:200]}")


class NioWhatsAppSession:
    """Sessão Playwright reutilizável para processar vários pedidos em sequência."""

    def __init__(self) -> None:
        self._playwright = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> NioWhatsAppSession:
        profile = _profile_dir()
        if not profile:
            raise RuntimeError("WHATSAPP_NIO_PROFILE_DIR não configurado.")
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile,
            headless=_headless(),
            slow_mo=30,
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=120000)
        if not _wait_login(self.page, timeout_sec=120):
            raise RuntimeError("WhatsApp Web não está logado. Escaneie o QR no perfil configurado.")
        state = _state_path()
        if state:
            try:
                self._context.storage_state(path=state)
            except Exception:
                logger.debug("Falha ao salvar storage state Nio.", exc_info=True)
        _dismiss_overlays(self.page)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    def reagendar(
        self,
        *,
        cpf: str,
        nome_esperado: str,
        cep_sufixo_esperado: str = "",
    ) -> ResultadoReagendamentoNio:
        if not self.page:
            return ResultadoReagendamentoNio(False, "erro", "Sessão WhatsApp não iniciada.")
        cpf_digits = "".join(ch for ch in cpf if ch.isdigit())
        hint = f"{cpf_digits[-5:-2]}-{cpf_digits[-2:]}" if len(cpf_digits) >= 5 else cpf_digits[-5:]
        return executar_reagendamento_pedido(
            self.page,
            cpf=cpf_digits,
            cpf_mask_hint=hint,
            nome_esperado=nome_esperado,
            cep_sufixo_esperado=cep_sufixo_esperado,
        )
