"""
Mapeia / preenche SmartRiser por BLOCO (1 obra = 1 complemento = nome do bloco).

Exemplos:
  # Só preencher modal + coords (sem salvar obra)
  .venv\\Scripts\\python.exe scripts\\mapear_vtop_smartriser.py --payload tmp_vtop_payload_cdoi_20.json --bloco "BLOCO 05" --ate coords --salvar-coords

  # Obra já criada: abrir, preencher Cadastro e salvar etapa
  .venv\\Scripts\\python.exe scripts\\mapear_vtop_smartriser.py --payload tmp_vtop_payload_cdoi_20.json --bloco "BLOCO 05" --obra-id 9416 --ate salvar
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from crm_app.services_vtop_smartriser import (  # noqa: E402
    VtopStatus,
    get_vtop_service,
    payload_para_bloco,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", default=str(BASE / "tmp_vtop_payload_cdoi_20.json"))
    parser.add_argument("--bloco", required=True, help='Ex.: "BLOCO 05"')
    parser.add_argument(
        "--obra-id",
        default="",
        help="Se informado, abre obra.jsp?id=… e pula criação do modal.",
    )
    parser.add_argument(
        "--ate",
        default="coords",
        help="Para após passo (coords | cadastro | salvar | validar).",
    )
    parser.add_argument("--com-anexos", action="store_true")
    parser.add_argument(
        "--carta",
        default="",
        help="Caminho local da carta (sobrescreve link_carta do payload).",
    )
    parser.add_argument(
        "--fachada",
        default="",
        help="Caminho local da fachada (sobrescreve link_fachada do payload).",
    )
    parser.add_argument(
        "--salvar-coords",
        action="store_true",
        help="Após preencher lat/long, clica Procurar e Salvar do mapa (aceita confirm).",
    )
    parser.add_argument(
        "--salvar-obra",
        action="store_true",
        help="Permite criar obra (#b_criar_obra) no fluxo completo.",
    )
    args = parser.parse_args()

    obra_id = (args.obra_id or "").strip()
    bloqueados: set[str] = set()
    if not obra_id:
        bloqueados.update({"validar", "fim"})
        if not args.salvar_obra:
            bloqueados.update({"salvar_obra", "coords_pos_salvar", "cadastro", "salvar"})
    else:
        if args.ate != "validar":
            bloqueados.add("validar")

    if args.ate in bloqueados:
        print(
            f"--ate {args.ate} bloqueado. "
            "Use --obra-id ID --ate salvar|validar  OU  --salvar-obra --ate cadastro"
        )
        return 2

    path = Path(args.payload)
    if not path.exists():
        print("Payload não encontrado:", path)
        return 2

    base = json.loads(path.read_text(encoding="utf-8"))
    if args.carta:
        base["link_carta"] = args.carta
    if args.fachada:
        base["link_fachada"] = args.fachada
    if not args.com_anexos and not args.carta and not args.fachada:
        base["link_carta"] = ""
        base["link_fachada"] = ""

    payload = payload_para_bloco(base, args.bloco)
    payload["salvar_coords"] = bool(args.salvar_coords)
    if args.com_anexos or args.carta or args.fachada:
        payload["com_anexos"] = True
        payload["anexar_arquivos"] = True
    if obra_id:
        payload["obra_id"] = obra_id

    print("CDOI:", payload.get("cdoi_id"), payload.get("nome_condominio"))
    print("Bloco/obra:", payload["complemento"])
    print("UMS (andares x aptos):", payload["andares"], "x", payload["aptos"], "=", payload["total_hps"])
    print("Lat/Long:", payload.get("latitude"), payload.get("longitude"))
    print(
        "Somente até:",
        args.ate,
        "| obra_id:",
        obra_id or "(nova)",
        "| Salvar coords:",
        args.salvar_coords,
    )

    svc = get_vtop_service()
    st = svc.get_state()
    if st.get("status") not in ("idle", "done", "error", None):
        print("Fechando browser anterior…")
        svc.fechar_navegador(manter_sessao=True)

    result = svc.iniciar(
        cdoi_id=int(payload.get("cdoi_id") or 20),
        payload=payload,
        forcar_login=False,
        somente_ate=args.ate,
    )
    if not result.get("ok"):
        print("Falha:", result)
        return 1

    FLAG_SENHA = BASE / "tmp_vtop_senha_pronta.flag"
    if FLAG_SENHA.exists():
        FLAG_SENHA.unlink()

    for _ in range(900):
        st = svc.get_state()
        print(
            f"[{st.get('status')}] {st.get('step')} | {st.get('message')} | extras={st.get('extras')}",
            flush=True,
        )
        if st.get("status") == VtopStatus.AWAITING_CREDENTIALS.value:
            print(
                "\n>>> Sessão pediu login. Digite a senha no Chromium e avise no chat,\n"
                f">>> ou crie o flag: {FLAG_SENHA}\n",
                flush=True,
            )
            if FLAG_SENHA.exists():
                svc.signal_senha_pronta()
                try:
                    FLAG_SENHA.unlink()
                except OSError:
                    pass
        if st.get("status") in (
            VtopStatus.DONE.value,
            VtopStatus.ERROR.value,
            VtopStatus.PAUSED.value,
        ):
            break
        time.sleep(1)

    print("FINAL:", json.dumps(svc.get_state(), ensure_ascii=False, indent=2))
    return 0 if svc.get_state().get("status") != VtopStatus.ERROR.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
