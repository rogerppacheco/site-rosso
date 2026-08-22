"""
Abre WhatsApp Web (Playwright) para mapear conversa com Nio (21 3605-1000).

Uso:
  python scripts/explorar_whatsapp_web_nio.py
  python scripts/explorar_whatsapp_web_nio.py --send-oi
  python scripts/explorar_whatsapp_web_nio.py --keep-open

Na 1ª execução, escaneie o QR Code no celular.
A sessão fica em .playwright_whatsapp_state.json e .playwright_whatsapp_profile/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

BASE_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = BASE_DIR / ".playwright_whatsapp_state.json"
PROFILE_DIR = BASE_DIR / ".playwright_whatsapp_profile"
OUT_DIR = BASE_DIR / "tmp_whatsapp_nio_map"
NIO_NUMBER_DISPLAY = "21 3605-1000"
NIO_NUMBER_RAW = "552136051000"
NIO_TITLE_HINTS = ("3605-1000", "3605 1000", "36051000", "nio")


def _screenshot(page: Page, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    page.screenshot(path=str(path), full_page=False)
    return path


def _dump_html(page: Page, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(page.content(), encoding="utf-8")
    return path


def _is_logged_in(page: Page) -> bool:
    markers = [
        "#pane-side",
        '[data-testid="chat-list"]',
        '[aria-label="Lista de conversas"]',
        '[aria-label="Chat list"]',
        'div[contenteditable="true"][data-tab="3"]',
        'div[contenteditable="true"][aria-label*="pesquisa" i]',
        'div[contenteditable="true"][aria-label*="Search" i]',
        '[data-icon="new-chat-outline"]',
        '[data-icon="chat"]',
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
        print("Aguardando inbox do WhatsApp Web...", flush=True)
        page.wait_for_timeout(2000)
    return False


def _chat_rows(page: Page) -> Locator:
    for sel in (
        '#pane-side [role="listitem"]',
        '[data-testid="cell-frame-container"]',
        '#pane-side [aria-label][role="row"]',
    ):
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc
    return page.locator('#pane-side [role="listitem"]')


def _row_title(row: Locator) -> str:
    for sel in (
        'span[title]',
        '[data-testid="cell-frame-title"]',
        'span[dir="auto"]',
    ):
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


def _list_chats(page: Page, limit: int = 40) -> list[dict[str, str]]:
    chats: list[dict[str, str]] = []
    rows = _chat_rows(page)
    count = min(rows.count(), limit)
    for i in range(count):
        row = rows.nth(i)
        title = _row_title(row)
        preview = ""
        try:
            lines = [ln.strip() for ln in (row.inner_text() or "").split("\n") if ln.strip()]
            if len(lines) > 1:
                preview = " | ".join(lines[1:4])
        except Exception:
            preview = ""
        chats.append({"index": str(i), "title": title, "preview": preview[:200]})
    return chats


def _dismiss_overlays(page: Page) -> None:
    """Fecha diálogos do WhatsApp Web que interceptam clique."""
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    labels = [
        "Continuar",
        "OK",
        "Ok",
        "Fechar",
        "Agora não",
        "Usar o WhatsApp Web",
        "Usar WhatsApp Web",
        "Entendi",
        "Não agora",
        "Close",
        "Continue",
        "Got it",
    ]
    for label in labels:
        loc = page.get_by_role("button", name=label)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(300)
        except Exception:
            continue
    try:
        dialog = page.locator('div[role="dialog"] button').first
        if dialog.count() > 0 and dialog.is_visible():
            dialog.click(timeout=2000)
            page.wait_for_timeout(300)
    except Exception:
        pass
    page.keyboard.press("Escape")


def _conversation_panel_open(page: Page) -> bool:
    """True se o painel direito é uma conversa (não o card 'Baixar WhatsApp')."""
    try:
        if page.locator("#main footer div[contenteditable='true']").count() > 0:
            return True
        if page.locator("#main [data-pre-plain-text]").count() > 0:
            return True
        header = page.locator("#main header")
        if header.count() == 0:
            return False
        text = (header.inner_text() or "").lower()
        return any(h.lower() in text for h in NIO_TITLE_HINTS)
    except Exception:
        return False


def _ensure_nio_conversation_open(page: Page) -> bool:
    """Clica/busca/abre o chat da Nio até o compositor aparecer."""
    _dismiss_overlays(page)
    if _click_chat_by_title(page, NIO_TITLE_HINTS) and _conversation_panel_open(page):
        return True
    print("Painel da conversa nao abriu; tentando busca...", flush=True)
    for query in ("3605-1000", "Nio", "21 3605"):
        _dismiss_overlays(page)
        if _open_chat_by_search(page, query) and _conversation_panel_open(page):
            return True
    print("Busca falhou; abrindo via /send?phone=...", flush=True)
    page.goto(
        f"https://web.whatsapp.com/send?phone={NIO_NUMBER_RAW}&text=&type=phone_number&app_absent=0",
        timeout=90000,
    )
    page.wait_for_timeout(6000)
    _dismiss_overlays(page)
    return _conversation_panel_open(page)


def _click_chat_by_title(page: Page, hints: tuple[str, ...]) -> bool:
    _dismiss_overlays(page)
    rows = _chat_rows(page)
    count = rows.count()
    for i in range(count):
        row = rows.nth(i)
        title = _row_title(row).lower()
        if any(h.lower() in title for h in hints):
            try:
                row.click(timeout=8000)
            except Exception:
                try:
                    row.click(timeout=5000, force=True)
                except Exception as exc:
                    print(f"Falha ao clicar no chat Nio: {exc}", flush=True)
                    return False
            page.wait_for_timeout(1500)
            return True
    return False


def _open_search(page: Page) -> Locator | None:
    selectors = [
        'div[contenteditable="true"][data-tab="3"]',
        'div[contenteditable="true"][aria-label*="pesquisa" i]',
        'div[contenteditable="true"][aria-label*="Search" i]',
        '[data-testid="chat-list-search"]',
        'div[role="textbox"][aria-label*="pesquisa" i]',
        'button[aria-label*="Pesquisar" i]',
        'button[aria-label*="Search" i]',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() == 0:
                continue
            loc.click(timeout=5000)
            page.wait_for_timeout(400)
            editable = page.locator('div[contenteditable="true"][data-tab="3"]').first
            if editable.count() > 0:
                return editable
            return loc
        except Exception:
            continue
    return None


def _open_chat_by_search(page: Page, query: str) -> bool:
    search = _open_search(page)
    if search is None:
        return False
    try:
        search.fill("")
    except Exception:
        pass
    search.type(query, delay=40)
    page.wait_for_timeout(1800)
    rows = _chat_rows(page)
    if rows.count() == 0:
        return False
    rows.first.click()
    page.wait_for_timeout(1500)
    return True


def _extract_messages(page: Page, limit: int = 200) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    seen: set[str] = set()
    bubbles = page.locator("#main [data-pre-plain-text]")
    count = bubbles.count()
    if count == 0:
        bubbles = page.locator(
            "#main [data-testid='msg-container'], "
            "#main div.message-in, "
            "#main div.message-out"
        )
        count = bubbles.count()
    start = max(0, count - limit)
    for i in range(start, count):
        bubble = bubbles.nth(i)
        pre = ""
        try:
            pre = bubble.get_attribute("data-pre-plain-text") or ""
        except Exception:
            pre = ""
        try:
            html_class = bubble.get_attribute("class") or ""
        except Exception:
            html_class = ""
        direction = "in"
        if "message-out" in html_class or (pre.startswith("[") and "21 3605" not in pre):
            # outgoing usually contains the logged-in contact, not the Nio number
            if "+55 21 3605-1000" not in pre and "21 3605-1000" not in pre:
                direction = "out"
        if "+55 21 3605-1000" in pre or "21 3605-1000" in pre:
            direction = "in"
        text = ""
        try:
            text_el = bubble.locator("span.selectable-text.copyable-text, span.selectable-text").first
            if text_el.count():
                text = text_el.inner_text()
            else:
                text = bubble.inner_text()
        except Exception:
            try:
                text = bubble.inner_text()
            except Exception:
                text = ""
        key = f"{pre}|{(text or '').strip()}"
        if key in seen:
            continue
        seen.add(key)
        button_labels: list[str] = []
        try:
            for btn in bubble.locator("button, [role='button']").all()[:12]:
                label = (btn.inner_text() or "").strip()
                if label:
                    button_labels.append(label[:80])
        except Exception:
            pass
        msgs.append(
            {
                "direction": direction,
                "pre": pre.strip(),
                "text": (text or "").strip(),
                "buttons": button_labels,
            }
        )
    return msgs


def _scroll_chat_history(page: Page, rounds: int = 25) -> None:
    """Sobe o painel de mensagens para forçar o WhatsApp a carregar o histórico."""
    pane_selectors = [
        "#main div[role='application']",
        "#main .copyable-area",
        "[data-testid='conversation-panel-messages']",
        "#main",
    ]
    pane = None
    for sel in pane_selectors:
        loc = page.locator(sel).first
        if loc.count() > 0:
            pane = loc
            break
    if pane is None:
        return
    _dismiss_overlays(page)
    try:
        pane.click(timeout=3000, force=True)
    except Exception:
        pass
    prev_count = 0
    stable = 0
    for _ in range(rounds):
        page.keyboard.press("Home")
        page.mouse.wheel(0, -4000)
        page.wait_for_timeout(700)
        count = page.locator("#main [data-pre-plain-text]").count()
        if count <= prev_count:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
            prev_count = count
            print(f"Histórico carregado: {count} mensagens...", flush=True)


def _send_text(page: Page, text: str) -> bool:
    compose_selectors = [
        'div[contenteditable="true"][data-tab="10"]',
        'div[contenteditable="true"][aria-label*="mensagem" i]',
        'div[contenteditable="true"][aria-placeholder*="mensagem" i]',
        'div[contenteditable="true"][aria-label*="Type a message" i]',
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Explorar WhatsApp Web — conversa Nio")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--send-oi", action="store_true", help='Envia "oi" no chat da Nio')
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--keep-open", action="store_true", help="Mantém o browser aberto")
    args = parser.parse_args()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Perfil persistente: WhatsApp Web precisa de IndexedDB, não só cookies.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=args.headless,
            slow_mo=50,
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=120000)

        if not _wait_login(page, timeout_sec=600 if not args.headless else 40):
            print("Login não detectado a tempo.", file=sys.stderr)
            _screenshot(page, "login_timeout.png")
            _dump_html(page, "login_timeout.html")
            if not args.keep_open:
                context.close()
            return 1

        try:
            context.storage_state(path=str(STATE_PATH))
        except Exception:
            pass
        print(f"Sessão OK. State: {STATE_PATH}")
        _dismiss_overlays(page)
        _screenshot(page, "inbox.png")

        chats = _list_chats(page)
        print(f"\n=== {len(chats)} conversas visíveis ===")
        for c in chats:
            print(f"  [{c['index']}] {c['title']} — {c['preview'][:70]}")

        report: dict = {"chats": chats, "nio": None, "messages": [], "oi_enviado": False}
        (OUT_DIR / "chats.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if args.list_only:
            if not args.keep_open:
                context.close()
            return 0

        opened = _ensure_nio_conversation_open(page)
        _screenshot(page, "nio_chat_aberto.png")
        print(f"Chat Nio aberto: {opened}")
        try:
            sync_label = page.get_by_text("Sincronizando mensagens", exact=False)
            if sync_label.count() > 0:
                sync_label.first.click(timeout=3000)
                page.wait_for_timeout(8000)
        except Exception:
            pass
        _dismiss_overlays(page)
        try:
            _scroll_chat_history(page)
        except Exception as exc:
            print(f"Scroll do historico falhou: {exc}", flush=True)
        _screenshot(page, "nio_historico.png")

        if args.send_oi:
            ok = _send_text(page, "oi")
            report["oi_enviado"] = ok
            print(f'Envio de "oi": {ok}')
            page.wait_for_timeout(6000)
            _screenshot(page, "nio_apos_oi.png")

        messages = _extract_messages(page)
        report["messages"] = messages
        report["nio"] = {"number": NIO_NUMBER_RAW, "display": NIO_NUMBER_DISPLAY}
        out_path = OUT_DIR / "nio_conversa_map.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _dump_html(page, "nio_chat.html")

        print(f"\n=== {len(messages)} mensagens/blocos capturados ===")
        for m in messages[-60:]:
            arrow = "OUT" if m.get("direction") == "out" else "IN"
            preview = (m.get("text") or "").replace("\n", " ")[:180]
            buttons = m.get("buttons") or []
            extra = f" | botoes={buttons}" if buttons else ""
            line = f"  [{arrow}] {preview}{extra}\n"
            sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        print(f"\nRelatório: {out_path}")

        try:
            context.storage_state(path=str(STATE_PATH))
        except Exception:
            pass

        if args.keep_open:
            print("Browser permanece aberto. Ctrl+C para encerrar.", flush=True)
            page.wait_for_timeout(300000)
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
