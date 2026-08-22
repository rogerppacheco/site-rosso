"""Renova o arquivo .playwright_state.json abrindo o site da Nio visivelmente.
Resolva o captcha/login manualmente e pressione Enter para salvar o novo storage_state.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
SITE_URL = "https://negociacao.niointernet.com.br/negociar"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera novo .playwright_state.json apos login manual")
    parser.add_argument("--cpf", help="CPF/CNPJ para preencher no campo inicial", default="")
    parser.add_argument("--state-path", help="Caminho do storage_state a salvar", default=".playwright_state.json")
    parser.add_argument("--headless", help="Executa headless (normalmente deixe desativado)", action="store_true")
    parser.add_argument("--slow-mo", help="Delay em ms entre acoes (ajuda a visualizar)", type=int, default=300)
    return parser.parse_args()


def renovar_state(cpf: str, state_path: Path, headless: bool, slow_mo: int) -> None:
    load_state: Optional[str] = str(state_path) if state_path.exists() else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
            storage_state=load_state,
        )
        page = context.new_page()

        print(f"Abrindo {SITE_URL} ...")
        page.goto(SITE_URL, wait_until="networkidle", timeout=30000)

        if cpf:
            try:
                input_box = page.locator('input[type="text"]').first
                input_box.fill(cpf)
                print(f"CPF/CNPJ preenchido: {cpf}")
            except Exception as exc:  # pragma: no cover
                print(f"Aviso: nao foi possivel preencher o CPF automaticamente ({exc})")

        print("\nResolva captcha/login manualmente no navegador.")
        input("Pressione Enter quando a pagina estiver autenticada...")

        try:
            ls = page.evaluate(
                "() => ({ token: localStorage.getItem('token'), apiServerUrl: localStorage.getItem('apiServerUrl') })"
            )
            print(f"Dados do localStorage: {ls}")
        except Exception as exc:  # pragma: no cover
            print(f"Aviso: nao foi possivel inspecionar localStorage ({exc})")

        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        print(f"Novo storage_state salvo em: {state_path}")

        browser.close()


def main() -> None:
    args = parse_args()
    renovar_state(cpf=args.cpf, state_path=Path(args.state_path), headless=args.headless, slow_mo=args.slow_mo)


if __name__ == "__main__":
    main()
