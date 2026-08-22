"""Testa o bot Nio com um pedido 7029 da esteira."""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from continuar_mapa_nio import _click_last_quick_reply, _tail, _wait_new  # noqa: E402
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
    _delta_texto,
    _parse_sucesso_agendado,
    _panel_text,
    _screenshot,
    _bloco_recente,
    _sessao_cpf_encerrada,
    _tem_prompt_cpf,
    _visible_buttons,
)
from playwright.sync_api import sync_playwright

VENDA_ID = 9972
OS = "10917510"
CPF = "03324537665"
CPF_MASK_HINT = "376-65"
NOME = "FABIENE"
OUT = OUT_DIR / "teste_9972.json"
PREFIX = "9972"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Testa agendamento no bot Nio")
    p.add_argument("--venda", type=int, default=VENDA_ID)
    p.add_argument("--os", dest="os_num", default=OS)
    p.add_argument("--cpf", default=CPF)
    p.add_argument("--nome", default=NOME)
    return p.parse_args()


def _cls_delta(antes: str, agora: str) -> dict:
    return _classificar(_delta_texto(antes, agora))


def _encerrar_com_sair(page, log: list, motivo: str, prefix: str) -> None:
    before = _panel_text(page)
    _send_text(page, "sair")
    texto = _wait_new(page, before, 15)
    _screenshot(page, f"{prefix}_sair_limpar.png")
    log.append({"passo": "sair_limpar", "motivo": motivo, "tail": _tail(texto)})
    print("Sessao limpa com sair:", motivo, flush=True)


def main() -> int:
    args = _parse_args()
    venda_id = int(args.venda)
    os_num = str(args.os_num)
    cpf = "".join(ch for ch in str(args.cpf) if ch.isdigit())
    nome = str(args.nome).strip().upper()
    cpf_mask_hint = f"{cpf[-5:-2]}-{cpf[-2:]}" if len(cpf) >= 5 else cpf[-5:]
    prefix = str(venda_id)
    out_path = OUT_DIR / f"teste_{venda_id}.json"
    print(f"Teste venda={venda_id} os={os_num} cpf=***{cpf[-5:]} nome={nome}", flush=True)

    STEPS_DIR.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    delta = ""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=40,
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=120000)
        if not _wait_login(page, 180):
            print("Login nao detectado", file=sys.stderr)
            _screenshot(page, f"{prefix}_login.png")
            ctx.close()
            return 1
        try:
            ctx.storage_state(path=str(STATE_PATH))
        except Exception:
            pass
        _dismiss_overlays(page)
        print("chat", _ensure_nio_conversation_open(page), flush=True)
        texto = _panel_text(page)
        recente = _bloco_recente(texto)
        delta = recente

        # Identificação: o bot sempre pergunta o ÚLTIMO CPF. Nunca mandar oi/sair
        # enquanto houver Sim/Não de CPF — isso gera "não entendi" e encerra a sessão.
        # Decidir só pelas últimas linhas (não pelo histórico).
        for etapa in range(8):
            texto = _panel_text(page)
            recente = _bloco_recente(texto)
            delta = recente
            print(
                f"ID {etapa} prompt_cpf={_tem_prompt_cpf(recente)} "
                f"encerrada={_sessao_cpf_encerrada(recente)} botoes={_visible_buttons(page)}",
                flush=True,
            )
            print(recente, flush=True)

            sucesso_id = _parse_sucesso_agendado(recente)
            if sucesso_id:
                print("SUCESSO no fluxo de identificacao:", sucesso_id, flush=True)
                delta = recente
                log.append({"passo": "sucesso_agendado", "dados": sucesso_id, "tail": recente})
                _encerrar_com_sair(page, log, "sucesso_tudo_certo", prefix)
                break

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
                _screenshot(page, f"{prefix}_04_cpf.png")
                print("APOS CPF:\n", _bloco_recente(texto), flush=True)
                log.append({"passo": "enviar_cpf", "tail": _bloco_recente(texto), "cls": _classificar(_bloco_recente(texto))})
                continue

            if _sessao_cpf_encerrada(recente) and not pede_cpf:
                before = texto
                _send_text(page, "oi")
                texto = _wait_new(page, before, 28)
                _screenshot(page, f"{prefix}_oi_{etapa}.png")
                log.append({"passo": "oi_reinicio", "tail": _bloco_recente(texto), "cls": _classificar(_bloco_recente(texto))})
                continue

            if _tem_prompt_cpf(recente):
                before = texto
                if cpf_mask_hint in recente:
                    clicado = _click_last_quick_reply(page, ("Sim",))
                    print("Sim no CPF alvo:", clicado, flush=True)
                else:
                    clicado = _click_last_quick_reply(page, ("Não", "Nao"))
                    print("Nao no ultimo CPF da sessao:", clicado, flush=True)
                texto = _wait_new(page, before, 28)
                _screenshot(page, f"{prefix}_id_{etapa}.png")
                log.append({"passo": "prompt_cpf", "clicado": clicado, "tail": _bloco_recente(texto), "cls": _classificar(_bloco_recente(texto))})
                continue

            if "até mais" in dlow or "ate mais" in dlow:
                before = texto
                _send_text(page, "oi")
                texto = _wait_new(page, before, 28)
                _screenshot(page, f"{prefix}_oi_{etapa}.png")
                log.append({"passo": "oi_apos_ate_mais", "tail": _bloco_recente(texto), "cls": _classificar(_bloco_recente(texto))})
                continue

            break

        delta = _bloco_recente(_panel_text(page), 20)

        for i in range(4):
            cls = _classificar(delta)
            sucesso = _parse_sucesso_agendado(delta)
            print(f"LOOP {i} botoes={_visible_buttons(page)} cls={cls}\n{delta[-500:]}\n", flush=True)

            if sucesso:
                print("SUCESSO — nao clica Reagendar. Encerrando com sair.", sucesso, flush=True)
                log.append({"passo": "sucesso_agendado", "dados": sucesso, "tail": _tail(delta)})
                _encerrar_com_sair(page, log, "sucesso_tudo_certo", prefix)
                texto = _panel_text(page)
                break

            if cls.get("falha_sem_slot") or cls.get("bug_invalid_date") or cls.get("falha_consulta"):
                log.append({"passo": "falha", "cls": cls, "tail": _tail(delta)})
                _encerrar_com_sair(page, log, "falha_bot", prefix)
                break

            dlow = delta.lower()
            if "confirmar data" in dlow:
                before = texto
                clicado = _click_last_quick_reply(page, ("Confirmar data",))
                print("Confirmar data (so o mais novo):", clicado, flush=True)
                texto = _wait_new(page, before, 35)
                delta = _delta_texto(before, texto)
                _screenshot(page, f"{prefix}_07_confirmar.png")
                log.append({"passo": "confirmar_data", "clicado": clicado, "tail": _tail(delta), "cls": _classificar(delta)})
                continue

            if "boa notícia" in dlow or "boa noticia" in dlow or "primeira data disponível" in dlow:
                before = texto
                clicado = _click_last_quick_reply(page, ("Confirmar data",))
                print("Confirmar oferta:", clicado, flush=True)
                texto = _wait_new(page, before, 35)
                delta = _delta_texto(before, texto)
                _screenshot(page, f"{prefix}_09_confirmar_oferta.png")
                log.append({"passo": "confirmar_oferta", "clicado": clicado, "tail": _tail(delta), "cls": _classificar(delta)})
                continue

            # Menu "O que você gostaria de fazer?" SEM "Tudo certo" ainda: Reagendar
            if "o que você gostaria de fazer" in dlow or "o que voce gostaria de fazer" in dlow:
                if _parse_sucesso_agendado(delta):
                    continue
                before = texto
                clicado = _click_last_quick_reply(page, ("Reagendar", "Agendar"))
                print("Menu acao:", clicado, flush=True)
                texto = _wait_new(page, before, 35)
                delta = _delta_texto(before, texto)
                _screenshot(page, f"{prefix}_08_menu_{i}.png")
                log.append({"passo": "menu", "clicado": clicado, "tail": _tail(delta), "cls": _classificar(delta)})
                continue

            break

        final = _tail(_panel_text(page), 1200)
        _screenshot(page, f"{prefix}_19_final.png")
        ultimo_sucesso = None
        for p in reversed(log):
            if p.get("passo") == "sucesso_agendado":
                ultimo_sucesso = p.get("dados")
                break
        resultado = {
            "venda_id": venda_id,
            "os": os_num,
            "cpf": cpf,
            "nome_esperado": nome,
            "sucesso": ultimo_sucesso,
            "classificacao_final": _classificar(delta),
            "tail_final": final,
            "passos": log,
        }
        out_path.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print("FINAL cls", resultado["classificacao_final"], flush=True)
        print("TAIL FINAL:\n", final, flush=True)
        print("Salvo", out_path, flush=True)
        page.wait_for_timeout(15000)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
