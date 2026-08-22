"""Continua o fluxo no bot Nio a partir do protocolo: Reagendar -> slots ou falha."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explorar_whatsapp_web_nio import (  # noqa: E402
    OUT_DIR,
    PROFILE_DIR,
    STATE_PATH,
    _dismiss_overlays,
    _ensure_nio_conversation_open,
    _send_text,
    _wait_login,
)
from mapear_bot_nio import (  # noqa: E402
    STEPS_DIR,
    _classificar,
    _click_botao_mais_novo,
    _panel_text,
    _screenshot,
    _visible_buttons,
)

from playwright.sync_api import Page, sync_playwright

OUT = OUT_DIR / "mapa_reagendamento_cont.json"


def _click_last_quick_reply(page: Page, labels: tuple[str, ...]) -> str | None:
    """Clica o botão mais novo visível (mais perto do compositor), nunca o histórico."""
    return _click_botao_mais_novo(page, labels)


def _wait_new(page: Page, before: str, timeout_sec: int = 28) -> str:
    """Espera texto novo e ainda ~5s de estabilidade (o bot manda 2–3 msgs em sequência)."""
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


def _tail(texto: str, n: int = 900) -> str:
    t = texto or ""
    return t[-n:]


def main() -> int:
    STEPS_DIR.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=40,
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=120000)
        if not _wait_login(page, timeout_sec=180):
            print("Login nao detectado.", file=sys.stderr)
            _screenshot(page, "10_login.png")
            context.close()
            return 1
        try:
            context.storage_state(path=str(STATE_PATH))
        except Exception:
            pass
        _dismiss_overlays(page)
        print("Chat:", _ensure_nio_conversation_open(page), flush=True)
        page.wait_for_timeout(4000)
        texto = _panel_text(page)
        _screenshot(page, "10_estado.png")
        print("TAIL:\n", _tail(texto, 700), flush=True)
        log.append({"passo": "estado", "tail": _tail(texto), "botoes": _visible_buttons(page), "cls": _classificar(texto)})

        # Se o menu ainda não veio, pede Reagendar.
        tail = _tail(texto, 500).lower()
        if "o que você gostaria de fazer" not in tail and "reagendar" not in tail[-200:]:
            before = texto
            _send_text(page, "Reagendar")
            texto = _wait_new(page, before, 30)
            _screenshot(page, "11_reagendar.png")
            print("Apos Reagendar TAIL:\n", _tail(texto, 700), flush=True)
            log.append({"passo": "enviar_reagendar", "tail": _tail(texto), "botoes": _visible_buttons(page), "cls": _classificar(texto)})

        # Confirma CPF se perguntar (clica o último Sim).
        for i in range(3):
            tail = _tail(texto, 400).lower()
            if "é pra esse que você quer atendimento" in tail or "e pra esse que voce quer atendimento" in tail:
                before = texto
                clicado = _click_last_quick_reply(page, ("Sim",))
                print("Clicou CPF:", clicado, flush=True)
                texto = _wait_new(page, before, 30)
                _screenshot(page, f"12_cpf_{i}.png")
                log.append({"passo": "sim_cpf", "clicado": clicado, "tail": _tail(texto), "cls": _classificar(texto)})
                continue
            if "digite seu cpf" in tail:
                print("Bot pediu CPF manual — parando (nao inventar CPF).", flush=True)
                break
            break

        # Se aparecer menu de acao, clica Reagendar (ultimo).
        tail = _tail(texto, 400).lower()
        if "o que você gostaria de fazer" in tail or "o que voce gostaria de fazer" in tail:
            before = texto
            clicado = _click_last_quick_reply(page, ("Reagendar",))
            if not clicado:
                _send_text(page, "Reagendar")
                clicado = "Reagendar(texto)"
            texto = _wait_new(page, before, 35)
            _screenshot(page, "13_menu_reagendar.png")
            print("Menu Reagendar:", clicado, "\n", _tail(texto, 700), flush=True)
            log.append({"passo": "menu_reagendar", "clicado": clicado, "tail": _tail(texto), "cls": _classificar(texto)})

        # Sem slot: Tentar novamente uma vez.
        tail = _tail(texto, 500).lower()
        if "não encontramos datas" in tail or "nao encontramos datas" in tail:
            before = texto
            clicado = _click_last_quick_reply(page, ("Tentar novamente",))
            print("Tentar novamente:", clicado, flush=True)
            texto = _wait_new(page, before, 35)
            _screenshot(page, "14_tentar_novamente.png")
            log.append({"passo": "tentar_novamente", "clicado": clicado, "tail": _tail(texto), "cls": _classificar(texto)})

        OUT.write_text(json.dumps({"passos": log}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Salvo {OUT}", flush=True)
        print("TAIL FINAL:\n", _tail(_panel_text(page), 900), flush=True)
        _screenshot(page, "19_final.png")
        page.wait_for_timeout(20000)
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
