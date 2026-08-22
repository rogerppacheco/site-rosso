"""
Preenche Cadastro + anexa + valida obras já lançadas (et. 1) no SmartRiser.

Pré-venda = ceil(18% × QUANTIDADE UMS da obra).

Ex.:
  .venv\\Scripts\\python.exe scripts\\preencher_blocos_cadastro_vtop.py ^
    --payload tmp_vtop_payload_cdoi_20.json ^
    --blocos "BLOCO 1,BLOCO 2,BLOCO 3,BLOCO 4"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from playwright.sync_api import sync_playwright  # noqa: E402

from crm_app.services_vtop_smartriser import (  # noqa: E402
    VTOP_SMARTRISER_URL,
    VtopSmartRiserService,
    _storage_state_path,
    calcular_pre_venda_bloco,
    payload_para_bloco,
)


def _norm_bloco(nome: str) -> str:
    s = (nome or "").strip().upper()
    m = re.match(r"BLOCO\s*0*(\d+)$", s)
    if m:
        return f"BLOCO {int(m.group(1))}"
    return s


def _abrir_brownfield(page) -> None:
    page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if page.locator("text=Brownfield").count():
        page.get_by_text(re.compile(r"Brownfield", re.I)).first.click()
        page.wait_for_timeout(2500)
    page.evaluate(
        """() => {
          const mg = document.querySelector("input[value='MG']");
          if (mg) { mg.disabled = false; if (!mg.checked) mg.click(); }
          const b = document.getElementById('b_pesquisa');
          if (b) b.disabled = false;
          if (typeof pesquisaObras === 'function') pesquisaObras();
        }"""
    )
    page.wait_for_timeout(4000)
    page.locator("text=Dezoito").first.wait_for(state="visible", timeout=60_000)


def _listar_obras_dezoito(page) -> List[Dict[str, Any]]:
    return page.evaluate(
        """() => {
          const byId = {};
          document.querySelectorAll('[onclick*=\"mostrarObra\"]').forEach(el => {
            const oc = el.getAttribute('onclick') || '';
            const m = oc.match(/mostrarObra\\(\\s*[\"']?(\\d+)/);
            if (!m) return;
            const id = m[1];
            const tr = el.closest('tr');
            const tds = tr
              ? [...tr.querySelectorAll('td')].map(td => (td.innerText || '').replace(/\\s+/g, ' ').trim())
              : [];
            const joined = tds.join(' | ');
            if (!joined.toUpperCase().includes('DEZOITO')) return;
            if (!byId[id]) byId[id] = { id, tds, joined };
          });
          return Object.values(byId);
        }"""
    )


def _match_obra(
    rows: List[Dict[str, Any]],
    *,
    logradouro: str,
    numero: str,
    bloco: str,
) -> Optional[Dict[str, Any]]:
    alvo = _norm_bloco(bloco)
    num_u = str(numero).strip()
    for r in rows:
        joined = (r.get("joined") or " | ".join(r.get("tds") or [])).upper()
        if logradouro.upper() not in joined:
            continue
        if num_u and num_u not in joined:
            continue
        for td in r.get("tds") or []:
            if _norm_bloco(td) == alvo:
                return r
        m = re.search(r"BLOCO\s*0*(\d+)", joined)
        if m and f"BLOCO {int(m.group(1))}" == alvo:
            return r
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", default=str(BASE / "tmp_vtop_payload_cdoi_20.json"))
    parser.add_argument("--logradouro", default="Rua Dezoito")
    parser.add_argument("--numero", default="185")
    parser.add_argument("--blocos", default="BLOCO 1,BLOCO 2,BLOCO 3,BLOCO 4")
    parser.add_argument("--carta", default="")
    parser.add_argument("--fachada", default="")
    parser.add_argument("--sem-anexos", action="store_true")
    parser.add_argument("--sem-validar", action="store_true")
    args = parser.parse_args()

    base = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    blocos = [b.strip() for b in args.blocos.split(",") if b.strip()]

    pasta = Path(
        r"C:\Users\rogge\OneDrive - Parceiros Oi\CDOI_Record_Vertical\CONQUISTA MONTE BELO_32113535"
    )
    carta = args.carta
    fachada = args.fachada
    if not args.sem_anexos:
        if not carta and pasta.exists():
            cands = list(pasta.glob("CARTA*.jfif"))
            carta = str(cands[0]) if cands else ""
        if not fachada and pasta.exists():
            cands = list(pasta.glob("FACHADA*.jfif"))
            fachada = str(cands[0]) if cands else ""

    resultados: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=40)
        context = browser.new_context(
            storage_state=_storage_state_path(),
            locale="pt-BR",
        )
        page = context.new_page()
        _abrir_brownfield(page)
        rows = _listar_obras_dezoito(page)
        Path(BASE / "tmp_vtop_lista_obras.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Obras Rua Dezoito: {len(rows)}")
        for r in rows:
            print(" ", r.get("id"), (r.get("joined") or "")[:140])

        svc = VtopSmartRiserService()
        svc.playwright = p
        svc.browser = browser
        svc.context = context
        svc.page = page

        for bloco in blocos:
            row = _match_obra(
                rows, logradouro=args.logradouro, numero=args.numero, bloco=bloco
            )
            if not row or not row.get("id"):
                print(f"[ERRO] Obra não encontrada: {bloco}")
                resultados.append({"bloco": bloco, "ok": False, "erro": "nao_encontrada"})
                continue

            obra_id = str(row["id"])
            ums_lista = None
            for td in reversed(row.get("tds") or []):
                if td.isdigit() and 1 <= int(td) <= 500:
                    ums_lista = int(td)
                    break
            prev = calcular_pre_venda_bloco(ums_lista or 0)
            print(f"=== {bloco} id={obra_id} ums={ums_lista} prevenda={prev}")

            try:
                try:
                    payload = payload_para_bloco(base, bloco)
                except ValueError:
                    m = re.match(r"BLOCO\s*0*(\d+)$", bloco.upper())
                    alt = f"BLOCO {int(m.group(1)):02d}" if m else bloco
                    payload = payload_para_bloco(base, alt)
                if ums_lista:
                    payload["total_hps"] = ums_lista
                    payload["pre_venda"] = prev
                payload["obra_id"] = obra_id
                payload["complemento"] = bloco
                payload["bloco_nome"] = bloco
                if not args.sem_anexos:
                    payload["com_anexos"] = True
                    payload["anexar_arquivos"] = True
                    payload["link_carta"] = carta
                    payload["link_fachada"] = fachada
                else:
                    payload["link_carta"] = ""
                    payload["link_fachada"] = ""

                svc.state.extras = {
                    "obra_id": obra_id,
                }
                svc._passo_abrir_obra_existente(obra_id)
                svc._passo_cadastro(payload)
                svc._passo_salvar_disquete()
                if not args.sem_validar:
                    svc._passo_validar()
                extras = dict(svc.state.extras)
                print(
                    f"OK {bloco}: etapa={extras.get('obra_etapa_apos_validar')} "
                    f"anexos={extras.get('anexos_ok')}"
                )
                resultados.append(
                    {
                        "bloco": bloco,
                        "obra_id": obra_id,
                        "ok": True,
                        "pre_venda": prev,
                        "extras": {
                            k: extras.get(k)
                            for k in (
                                "ums_obra",
                                "anexos_ok",
                                "anexos_falha",
                                "obra_etapa_apos_validar",
                                "cadastro_campos_ok",
                            )
                        },
                    }
                )
                _abrir_brownfield(page)
                rows = _listar_obras_dezoito(page)
            except Exception as exc:
                print(f"[ERRO] {bloco}: {exc}")
                resultados.append(
                    {"bloco": bloco, "obra_id": obra_id, "ok": False, "erro": str(exc)}
                )
                try:
                    _abrir_brownfield(page)
                    rows = _listar_obras_dezoito(page)
                except Exception:
                    pass

        out = BASE / "tmp_vtop_resultado_blocos_1a4.json"
        out.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
        context.storage_state(path=_storage_state_path())
        print("Resultado:", out)
        time.sleep(2)
        browser.close()

    ok = sum(1 for r in resultados if r.get("ok"))
    print(f"Concluído: {ok}/{len(blocos)} blocos")
    return 0 if ok == len(blocos) else 1


if __name__ == "__main__":
    raise SystemExit(main())
