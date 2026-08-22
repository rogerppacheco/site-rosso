"""
Teste visual da consulta Br Pronto (browser visível).
Usa um login do pool e um CPF informado.

Uso:
  set BRPRONTO_HEADLESS=false
  python scripts/testar_brpronto_bio.py --cpf 00000000000
  python scripts/testar_brpronto_bio.py --cpf 00000000000 --login TT828860
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from crm_app.pool_brpronto import obter_login_brpronto, liberar_login_brpronto
from crm_app.services_brpronto import consultar_biometria_brpronto
from usuarios.models import Usuario


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpf", required=True, help="CPF com 11 dígitos")
    parser.add_argument("--login", default="", help="Força um brpronto_login específico")
    parser.add_argument("--headless", action="store_true", help="Rodar sem UI")
    args = parser.parse_args()

    headless = args.headless
    bo = None
    lock_key = "teste:script"

    if args.login:
        bo = (
            Usuario.objects.filter(brpronto_login__iexact=args.login)
            .exclude(brpronto_senha__isnull=True)
            .exclude(brpronto_senha="")
            .first()
        )
        if not bo:
            print(f"Login {args.login} não encontrado com senha no cadastro.")
            sys.exit(1)
        print(f"Usando login forçado: {bo.brpronto_login} (user={bo.username})")
    else:
        bo, err = obter_login_brpronto(lock_key, origem="teste")
        if not bo:
            print(err)
            sys.exit(1)
        print(f"Pool alocou: {bo.brpronto_login} (user={bo.username})")

    try:
        print("Abrindo Chromium (acompanhe as telas)...")
        ok, msg, res = consultar_biometria_brpronto(
            login=bo.brpronto_login or "",
            senha=bo.brpronto_senha or "",
            cpf=args.cpf,
            dominio=bo.brpronto_dominio or "BrPronto",
            headless=headless,
            timeout_ms=90000,
        )
        print("sucesso=", ok)
        if msg:
            print("erro=", msg)
        print("aprovada=", res.get("aprovada"))
        print("data_apta=", res.get("data_mais_recente_apta"))
        print("n_registros=", len(res.get("registros") or []))
        for r in (res.get("registros") or [])[:5]:
            print(
                " -",
                r.get("protocolo"),
                r.get("resultado_analise"),
                r.get("data_envio"),
            )
    finally:
        if not args.login:
            liberar_login_brpronto(bo.id, lock_key)
        print("Lock liberado / logoff executado no serviço.")


if __name__ == "__main__":
    main()
