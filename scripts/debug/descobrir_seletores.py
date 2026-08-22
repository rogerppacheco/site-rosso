#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para descobrir os seletores corretos da página após consulta (Playwright).

Uso (a partir da raiz do projeto):
    python scripts/debug/descobrir_seletores.py <CPF>
    Ex.: python scripts/debug/descobrir_seletores.py 81721021604
"""
import os
import sys
import re

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from playwright.sync_api import sync_playwright


def descobrir_seletores(cpf):
    """Descobre seletores da página após consulta."""
    print("=" * 80)
    print(f"DESCOBRINDO SELETORES PARA CPF: {cpf}")
    print("=" * 80)

    NIO_BASE_URL = "https://www.niointernet.com.br/ajuda/servicos/segunda-via/"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        print("\n1. Navegando para a página...")
        page.goto(NIO_BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(2000)

        print("2. Preenchendo CPF...")
        input_cpf = page.locator("#cpf-cnpj").first
        input_cpf.fill(cpf)
        page.wait_for_timeout(500)

        print("3. Clicando em Consultar...")
        btn_consultar = page.locator('button[type="submit"]').first
        btn_consultar.click()

        print("4. Aguardando carregamento da página de resultado...")
        page.wait_for_url("**/resultado/**", timeout=15000)
        page.wait_for_timeout(3000)

        print("\n" + "=" * 80)
        print("ANALISANDO ELEMENTOS DA PÁGINA")
        print("=" * 80)

        html = page.content()

        print("\n📌 TODOS OS BOTÕES ENCONTRADOS:")
        print("-" * 80)
        buttons = page.locator("button").all()
        for i, btn in enumerate(buttons[:20], 1):
            try:
                text = btn.inner_text(timeout=1000)
                is_visible = btn.is_visible()
                classes = btn.get_attribute("class") or ""
                btn_id = btn.get_attribute("id") or ""
                if is_visible and text.strip():
                    print(f"\n{i}. Texto: '{text.strip()}'")
                    if btn_id:
                        print(f"   ID: #{btn_id}")
                    if classes:
                        print(f"   Classes: .{classes.split()[0] if classes.split() else ''}")
            except Exception:
                pass

        print("\n\n🔗 LINKS RELEVANTES:")
        print("-" * 80)
        links = page.locator("a").all()
        for i, link in enumerate(links[:20], 1):
            try:
                text = link.inner_text(timeout=1000)
                is_visible = link.is_visible()
                if is_visible and text.strip():
                    texto_limpo = text.strip().lower()
                    if any(
                        kw in texto_limpo
                        for kw in ["pagar", "boleto", "detalhes", "gerar", "download", "baixar"]
                    ):
                        print(f"\n{i}. Texto: '{text.strip()}'")
                        link_id = link.get_attribute("id") or ""
                        if link_id:
                            print(f"   ID: #{link_id}")
            except Exception:
                pass

        downloads_dir = os.path.join(_root, "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        html_path = os.path.join(downloads_dir, f"debug_seletores_{cpf}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n\n💾 HTML salvo em: {html_path}")

        print("\n" + "=" * 80)
        print("⏸️  Navegador aberto. Pressione Enter para fechar...")
        print("=" * 80)
        input()

        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/debug/descobrir_seletores.py <CPF>")
        sys.exit(1)
    cpf_limpo = re.sub(r"\D", "", sys.argv[1])
    if len(cpf_limpo) != 11:
        print(f"❌ CPF inválido. Deve ter 11 dígitos.")
        sys.exit(1)
    descobrir_seletores(cpf_limpo)
