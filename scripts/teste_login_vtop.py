"""
Teste seguro: só login V.top + salvar sessão Playwright.

Não preenche SmartRiser e NÃO faz logout.
Uso:

  .venv\\Scripts\\python.exe scripts\\teste_login_vtop.py

Quando o Chromium abrir na tela de login:
  1) Digite usuário/senha
  2) Crie o arquivo flag (ou avise no chat) para o script clicar em EFETUAR LOGIN:

     .venv\\Scripts\\python.exe -c "open(r'tmp_vtop_senha_pronta.flag','w').close()"
"""

from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from crm_app.services_vtop_smartriser import (  # noqa: E402
    VtopStatus,
    get_vtop_service,
    _storage_state_path,
)

FLAG_SENHA = os.path.join(BASE, "tmp_vtop_senha_pronta.flag")


def main() -> int:
    if os.path.exists(FLAG_SENHA):
        os.remove(FLAG_SENHA)

    svc = get_vtop_service()
    path = _storage_state_path()
    print("=" * 60)
    print("TESTE LOGIN V.top / SmartRiser (somente_ate=login)")
    print(f"Referência CDOI: #21 (só identificação — sem preencher obra)")
    print(f"Storage state: {path}")
    print(f"Já existe sessão? {os.path.exists(path)}")
    print("=" * 60)

    result = svc.iniciar(
        cdoi_id=21,
        payload={"cdoi_id": 21, "nome_condominio": "TESTE_LOGIN"},
        forcar_login=False,  # deve reutilizar .playwright_vtop_state.json
        somente_ate="login",
    )
    if not result.get("ok"):
        print("Falha ao iniciar:", result)
        return 1

    sinalizou = False
    for _ in range(900):  # até ~15 min
        st = svc.get_state()
        status = st.get("status")
        print(f"[{status}] {st.get('message')}", flush=True)

        if status == VtopStatus.AWAITING_CREDENTIALS.value and not sinalizou:
            print(
                "\n>>> Digite login/senha no Chromium.\n"
                f">>> Depois crie o flag: {FLAG_SENHA}\n"
                ">>> (ou avise no chat Cursor que já colocou a senha)\n",
                flush=True,
            )
            if os.path.exists(FLAG_SENHA):
                print("Flag detectada — clicando EFETUAR LOGIN…", flush=True)
                svc.signal_senha_pronta()
                sinalizou = True
                try:
                    os.remove(FLAG_SENHA)
                except OSError:
                    pass

        if status == VtopStatus.DONE.value:
            print("\nOK — sessão salva em:", path, flush=True)
            print("Não foi feito logout. Pode fechar o Chromium quando quiser.", flush=True)
            return 0
        if status == VtopStatus.ERROR.value:
            print("\nERRO:", st.get("error") or st.get("message"), flush=True)
            return 1
        time.sleep(1)

    print("Timeout.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
