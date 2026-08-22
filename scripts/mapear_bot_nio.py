"""Reabre o bot Nio (21 3605-1000), envia oi e mapeia sucesso x falha do reagendamento."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

# Estados do prompt de CPF (o bot sempre oferece o último CPF da sessão).
ESTADOS_CPF = {
    "perguntar_ultimo_cpf": "Encontrei o CPF XXX.XXX.376-65. É pra esse que você quer atendimento?",
    "nao_entendi_cpf": "Desculpa, não entendi. você quer continuar com o CPF XXX.XXX.376-65?",
    "cpf_nao_confirmado": "Poxa, como você não me confirmou o CPF, eu não consigo achar o cadastro no sistema.",
    "tente_mais_tarde": "Por favor, tente de novo mais tarde.",
    "consulta_indisponivel": "Ops! Meu sistema de consulta não está muito legal. Tente mais tarde, por favor.",
    "pedir_cpf_manual": "Por favor, digite seu CPF ou CNPJ.",
}


def _bloco_recente(texto: str, linhas: int = 10) -> str:
    """Últimas linhas visíveis, sem o histórico de outro CPF."""
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
SUCESSO_AGENDADO_RE = re.compile(
    r"Tudo certo,\s*(?P<nome>[^.]+)\.\s*"
    r".*?Sua visita está agendada pro endereço\s+(?P<endereco>.+?),\s*"
    r"(?P<data>\d{2}/\d{2}/\d{4}),\s*no período das\s+"
    r"(?P<inicio>\d{2}:\d{2})\s*às\s*(?P<fim>\d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)

# Reusa helpers do explorer
sys.path.insert(0, str(Path(__file__).resolve().parent))
from explorar_whatsapp_web_nio import (  # noqa: E402
    NIO_TITLE_HINTS,
    OUT_DIR,
    PROFILE_DIR,
    STATE_PATH,
    _dismiss_overlays,
    _ensure_nio_conversation_open,
    _send_text,
    _wait_login,
)

STEPS_DIR = OUT_DIR / "passos"
TRANSCRIPT = OUT_DIR / "mapa_reagendamento.json"

# Não clicar: transbordo humano / confirmação final de data real.
BOTOES_EVITAR = (
    "conversar agora",
    "falar com atendente",
    "atendente",
    "confirmar",
    "confirmar agendamento",
    "agendar",
)
BOTOES_PRIORIDADE = (
    "tentar novamente",
    "reagendar",
    "alterar data",
    "outra data",
    "ver datas",
    "continuar",
    "sim",
)


def _panel_text(page: Page) -> str:
    main = page.locator("#main")
    if main.count() == 0:
        return ""
    return (main.inner_text() or "").strip()


def _screenshot(page: Page, name: str) -> str:
    STEPS_DIR.mkdir(parents=True, exist_ok=True)
    path = STEPS_DIR / name
    page.screenshot(path=str(path), full_page=False)
    return str(path)


def _delta_texto(antes: str, agora: str) -> str:
    """Só o trecho novo desde a última ação — ignora histórico de outro CPF."""
    agora = agora or ""
    antes = antes or ""
    if agora.startswith(antes):
        return agora[len(antes):].strip()
    # O painel virtualizado muda o prefixo; usa o sufixo novo.
    return agora[-900:].strip()


def _parse_sucesso_agendado(texto: str) -> dict | None:
    """Sucesso definitivo: Tudo certo + endereço + data real + faixa. Aí só sair."""
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
        "tem_botao_reagendar": "reagendar" in (texto or "").lower(),
    }


def _footer_y(page: Page) -> float:
    try:
        box = page.locator("#main footer").first.bounding_box()
        if box:
            return float(box["y"])
    except Exception:
        pass
    return 10_000.0


def _botoes_visiveis_inferiores(page: Page) -> list[tuple[str, Locator, float]]:
    """Botões da conversa acima do compositor, do mais baixo (mais novo) para o mais alto."""
    footer_y = _footer_y(page)
    achados: list[tuple[str, Locator, float]] = []
    loc = page.locator("#main button, #main [role='button']")
    n = loc.count()
    for i in range(n):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            box = el.bounding_box()
            if not box:
                continue
            if box["y"] < 80 or box["y"] >= footer_y - 8:
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


def _click_button(page: Page, label: str) -> bool:
    return _click_botao_mais_novo(page, (label,)) is not None


def _click_botao_mais_novo(page: Page, labels: tuple[str, ...]) -> str | None:
    """Clica só o botão mais baixo (última mensagem visível) cujo texto está em labels.

    Botões antigos (ex.: Confirmar data do RYAN) ficam mais acima no chat e são ignorados.
    """
    wanted = {x.strip().lower() for x in labels}
    for texto, el, _y in _botoes_visiveis_inferiores(page):
        if texto.strip().lower() in wanted:
            try:
                el.click(timeout=4000)
                return texto
            except Exception:
                continue
    return None


def _wait_text_change(page: Page, before: str, timeout_sec: int = 25) -> str:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        page.wait_for_timeout(1000)
        now = _panel_text(page)
        if now and now != before and len(now) >= len(before):
            # nova mensagem no final
            if now not in before or now[-80:] != before[-80:]:
                return now
        if now and now != before:
            return now
    return _panel_text(page)


def _classificar(texto: str) -> dict[str, bool | str | dict | None]:
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
    encerrado = any(p in t for p in ("até mais", "ate mais", "tô 24h", "to 24h"))
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
        "encerrado": encerrado,
        "sucesso_agendado": sucesso_agendado,
        "sucesso_aparente": sucesso,
    }


def main() -> int:
    STEPS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
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
            print("Login nao detectado. Escaneie o QR.", file=sys.stderr)
            _screenshot(page, "00_login.png")
            context.close()
            return 1
        try:
            context.storage_state(path=str(STATE_PATH))
        except Exception:
            pass

        _dismiss_overlays(page)
        opened = _ensure_nio_conversation_open(page)
        print(f"Chat aberto: {opened}", flush=True)
        _screenshot(page, "01_chat.png")
        texto0 = _panel_text(page)
        botoes0 = _visible_buttons(page)
        log.append(
            {
                "passo": "abrir_chat",
                "texto": texto0[-2500:],
                "botoes": botoes0,
                "classificacao": _classificar(texto0),
            }
        )
        print("Botoes visiveis:", botoes0, flush=True)

        before = texto0
        ok = _send_text(page, "oi")
        print(f"oi enviado: {ok}", flush=True)
        texto1 = _wait_text_change(page, before, timeout_sec=30)
        _screenshot(page, "02_apos_oi.png")
        botoes1 = _visible_buttons(page)
        log.append(
            {
                "passo": "enviar_oi",
                "oi_enviado": ok,
                "texto": texto1[-2500:],
                "botoes": botoes1,
                "classificacao": _classificar(texto1),
            }
        )
        print("Apos oi botoes:", botoes1, flush=True)
        print("Classificacao:", _classificar(texto1), flush=True)

        # Segue o caminho de retry (não conversar com humano, não confirmar data).
        clicado = None
        for cand in botoes1:
            low = cand.lower()
            if any(e in low for e in BOTOES_EVITAR):
                continue
            if any(p in low for p in BOTOES_PRIORIDADE) or low in ("tentar novamente",):
                before = texto1
                if _click_button(page, cand):
                    clicado = cand
                    texto2 = _wait_text_change(page, before, timeout_sec=35)
                    _screenshot(page, "03_apos_botao.png")
                    botoes2 = _visible_buttons(page)
                    log.append(
                        {
                            "passo": "clicar_botao",
                            "botao": cand,
                            "texto": texto2[-2500:],
                            "botoes": botoes2,
                            "classificacao": _classificar(texto2),
                        }
                    )
                    print(f"Clicou [{cand}] botoes:", botoes2, flush=True)
                    print("Classificacao:", _classificar(texto2), flush=True)
                    break

        if clicado is None:
            print("Nenhum botao seguro para clicar (evitei atendente/confirmar).", flush=True)

        TRANSCRIPT.write_text(
            json.dumps(
                {
                    "objetivo": "Mapear sucesso vs falha do reagendamento no bot Nio",
                    "passos": log,
                    "regra_sucesso": [
                        "Mensagem com data/turno explícitos (ex.: 18/08/2026 à tarde) E verbo de confirmação (reagendado/confirmado/agendado para).",
                        "Não pode conter Invalid Date nem 'não encontramos datas'.",
                    ],
                    "regra_falha": [
                        "não encontramos datas / sem horários",
                        "Invalid Date",
                        "atendimento encerrado (Até mais)",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Mapa: {TRANSCRIPT}", flush=True)
        print("Browser aberto 90s para inspecao...", flush=True)
        page.wait_for_timeout(90000)
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
