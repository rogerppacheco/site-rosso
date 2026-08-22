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


def _tem_prompt_cpf(texto: str) -> bool:
    t = (texto or "").lower()
    return (
        "é pra esse que você quer atendimento" in t
        or "e pra esse que voce quer atendimento" in t
        or "quer continuar com o cpf" in t
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
    main = page.locator("#main")
    if main.count() == 0:
        return ""
    return (main.inner_text() or "").strip()


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
            loc.fill("")
            loc.type(text, delay=40)
            page.keyboard.press("Enter")
            page.wait_for_timeout(4000)
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
    _wait_new(page, before, 15)


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

    def reagendar(self, *, cpf: str, nome_esperado: str) -> ResultadoReagendamentoNio:
        if not self.page:
            return ResultadoReagendamentoNio(False, "erro", "Sessão WhatsApp não iniciada.")
        cpf_digits = "".join(ch for ch in cpf if ch.isdigit())
        hint = f"{cpf_digits[-5:-2]}-{cpf_digits[-2:]}" if len(cpf_digits) >= 5 else cpf_digits[-5:]
        return executar_reagendamento_pedido(
            self.page,
            cpf=cpf_digits,
            cpf_mask_hint=hint,
            nome_esperado=nome_esperado,
        )
