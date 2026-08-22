"""
Lança / conclui blocos no SmartRiser sem duplicar obras.

Prioridade para obter obra_id:
  1. CdoiBloco.vtop_obra_id (banco)
  2. Lista Brownfield (mesmo logradouro+número+complemento)
  3. Só então cria obra nova

Uso:
  .venv\\Scripts\\python.exe scripts\\lancar_blocos_restantes_vtop.py ^
    --cdoi-id 20 --somente "PORTARIA,GARAGEM,ADMINISTRAÇÃO,BLOCO 06,BLOCO 07"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
# Playwright sync usa event loop interno; ORM Django precisa disso no script
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import django

django.setup()

from playwright.sync_api import sync_playwright  # noqa: E402

from crm_app.models import CdoiBloco, CdoiSolicitacao  # noqa: E402
from crm_app.services_vtop_smartriser import (  # noqa: E402
    VTOP_SMARTRISER_URL,
    VtopSmartRiserService,
    _bloco_equiv,
    _norm_nome_bloco,
    _storage_state_path,
    calcular_pre_venda_bloco,
    montar_payload_cdoi,
    payload_para_bloco,
    persistir_vtop_obra_bloco,
)


def _abrir_brownfield(page, *, obrigatorio: bool = True) -> bool:
    page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    # Sessão expirada → IdP: espera login manual no Chromium local
    url = (page.url or "").lower()
    if "login" in url and "vtal" in url:
        print(
            "\n*** LOGIN V.tal necessário ***\n"
            "Digite usuário/senha no Chromium e conclua o login.\n"
            "Aguardando até 5 minutos…\n"
        )
        try:
            page.wait_for_url("**/appvtop/**", timeout=300_000)
            page.wait_for_timeout(2000)
            page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception:
            print(f"AVISO: login não concluído a tempo ({page.url})")
            if obrigatorio:
                raise RuntimeError("Sessão V.top expirada — faça login e rode de novo.")
            return False

    if page.locator("text=SmartRiser").count() and not page.locator("#addUmaObra").count():
        try:
            page.get_by_text("SmartRiser - Rede Inteligente Vertical", exact=False).first.click(
                timeout=5000
            )
            page.wait_for_timeout(2000)
        except Exception:
            try:
                page.get_by_text("SmartRiser", exact=False).first.click(timeout=5000)
                page.wait_for_timeout(2000)
            except Exception:
                page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

    if page.locator("text=Brownfield").count():
        page.get_by_text(re.compile(r"Brownfield", re.I)).first.click()
        page.wait_for_timeout(3000)

    page.evaluate(
        """() => {
          const mg = document.querySelector("input[value='MG']");
          if (mg) { mg.disabled = false; if (!mg.checked) mg.click(); }
          const b = document.getElementById('b_pesquisa');
          if (b) b.disabled = false;
          if (typeof pesquisaObras === 'function') pesquisaObras();
        }"""
    )
    page.wait_for_timeout(5000)
    try:
        # Trecho do endereço pode ser Diamante / Dezoito etc. — espera a grade
        page.locator("#addUmaObra, i.fa-square-plus.icone_obra").first.wait_for(
            state="visible", timeout=60_000
        )
    except Exception:
        print(f"AVISO: FAB não apareceu. URL={page.url}")
        if obrigatorio:
            return False
        return False
    fab = page.locator("#addUmaObra")
    if fab.count() == 0:
        fab = page.locator("i.fa-square-plus.icone_obra, button:has(i.fa-square-plus)")
    try:
        fab.first.wait_for(state="visible", timeout=30_000)
    except Exception:
        if obrigatorio:
            return False
    return True


def _garantir_smartriser_sessao(page) -> None:
    """Abre SmartRiser sem depender da grade Brownfield (para rota por obra_id)."""
    page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    url = (page.url or "").lower()
    if "login" in url and "vtal" in url:
        print(
            "\n*** LOGIN V.tal necessário ***\n"
            "Digite usuário/senha no Chromium e conclua o login.\n"
            "Aguardando até 5 minutos…\n"
        )
        page.wait_for_url("**/appvtop/**", timeout=300_000)
        page.wait_for_timeout(2000)
        page.goto(VTOP_SMARTRISER_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    if page.locator("text=SmartRiser").count() and "smartriser" not in url:
        try:
            page.get_by_text("SmartRiser", exact=False).first.click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception:
            pass



def _obras_no_endereco(page, logradouro: str, numero: str) -> Dict[str, str]:
    """
    Retorna mapa norm(complemento) → obra_id a partir da grade Brownfield.
    """
    tokens = [t for t in re.split(r"\s+", (logradouro or "").strip()) if len(t) >= 4]
    trecho = tokens[-1] if tokens else (logradouro or "Diamante")
    rows = page.evaluate(
        """(args) => {
          const { trecho, numero } = args;
          const byId = {};
          document.querySelectorAll('[onclick*=\"mostrarObra\"]').forEach(el => {
            const oc = el.getAttribute('onclick') || '';
            const m = oc.match(/mostrarObra\\(\\s*[\"']?(\\d+)/);
            if (!m) return;
            const id = m[1];
            const tr = el.closest('tr');
            const tds = tr
              ? [...tr.querySelectorAll('td')].map(td =>
                  (td.innerText || '').replace(/\\s+/g, ' ').trim())
              : [];
            const joined = tds.join(' | ');
            const ju = joined.toUpperCase();
            if (!ju.includes(String(trecho).toUpperCase())) return;
            if (numero && !ju.includes(String(numero))) return;
            if (!byId[id]) byId[id] = { id, tds, joined };
          });
          return Object.values(byId);
        }""",
        {"trecho": trecho, "numero": numero},
    )
    Path(BASE / "tmp_vtop_lista_obras.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    mapa: Dict[str, str] = {}
    for row in rows or []:
        oid = str(row.get("id") or "").strip()
        if not oid:
            continue
        for td in row.get("tds") or []:
            u = (td or "").strip().upper()
            if (
                u.startswith("BLOCO")
                or "PORTARIA" in u
                or "ADMINISTRA" in u
                or "GARAGEM" in u
            ):
                chave = _norm_nome_bloco(td)
                if chave and chave not in mapa:
                    mapa[chave] = oid
                break
    return mapa


def _resolver_obra_id(
    *,
    cdoi_id: int,
    nome: str,
    lista: Dict[str, str],
) -> str:
    for b in CdoiBloco.objects.filter(solicitacao_id=cdoi_id):
        if _bloco_equiv(b.nome_bloco, nome) and (b.vtop_obra_id or "").strip():
            return str(b.vtop_obra_id).strip()
    for chave, oid in lista.items():
        if _bloco_equiv(chave, nome) and oid:
            return str(oid).strip()
    return ""


def _lista_tem_bloco(lista: Dict[str, str], nome: str) -> bool:
    return any(_bloco_equiv(k, nome) for k in lista)


def _seed_ids_conhecidos(cdoi_id: int) -> int:
    """Importa obra_ids já capturados nos JSONs tmp do próprio CDOI."""
    arquivos = [
        BASE / f"tmp_vtop_resultado_cdoi_{cdoi_id}.json",
    ]
    if cdoi_id == 20:
        arquivos.extend(
            [
                BASE / "tmp_vtop_resultado_blocos_1a4.json",
                BASE / "tmp_vtop_resultado_lancar_restantes.json",
            ]
        )
    gravados = 0
    for path in arquivos:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data or []:
            if not item.get("ok"):
                continue
            oid = str(item.get("obra_id") or "").strip()
            nome = str(item.get("bloco") or "").strip()
            if not oid or not nome:
                continue
            etapa = item.get("etapa")
            if etapa is None and isinstance(item.get("extras"), dict):
                etapa = item["extras"].get("obra_etapa_apos_validar")
            if persistir_vtop_obra_bloco(cdoi_id, nome, oid, etapa=etapa):
                gravados += 1
    return gravados


def _fechar_abas_extras(context, svc: VtopSmartRiserService) -> None:
    lista = context.pages[0]
    for pg in list(context.pages)[1:]:
        try:
            pg.close()
        except Exception:
            pass
    svc.page = lista
    lista.bring_to_front()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdoi-id", type=int, default=20)
    parser.add_argument("--payload", default="", help="Opcional: JSON em vez do banco")
    parser.add_argument("--logradouro", default="")
    parser.add_argument("--numero", default="")
    parser.add_argument(
        "--somente",
        default="PORTARIA,GARAGEM,ADMINISTRAÇÃO,BLOCO 06,BLOCO 07",
        help='Lista "PORTARIA,GARAGEM"',
    )
    parser.add_argument("--sem-anexos", action="store_true")
    parser.add_argument("--sem-validar", action="store_true")
    parser.add_argument("--seed-only", action="store_true", help="Só grava IDs dos JSONs no banco")
    parser.add_argument(
        "--pasta-anexos",
        default="",
        help="Pasta local com CARTA* e FACHADA* (OneDrive CDOI_Record_Vertical/...)",
    )
    parser.add_argument(
        "--nao-criar",
        action="store_true",
        help="Só reusa se achar o complemento na lista; nunca cria obra nova.",
    )
    args = parser.parse_args()

    cdoi_id = int(args.cdoi_id)
    seeded = _seed_ids_conhecidos(cdoi_id)
    print(f"Seed de IDs conhecidos: {seeded} vínculos")

    if args.seed_only:
        for b in CdoiBloco.objects.filter(solicitacao_id=cdoi_id).order_by("nome_bloco"):
            print(f"  {b.nome_bloco}: obra_id={b.vtop_obra_id or '-'} etapa={b.vtop_etapa}")
        return 0

    if args.payload:
        base = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        base["cdoi_id"] = cdoi_id
    else:
        cdoi = CdoiSolicitacao.objects.prefetch_related("blocos").get(pk=cdoi_id)
        base = montar_payload_cdoi(cdoi)

    logradouro = args.logradouro or base.get("logradouro") or "Rua Dezoito"
    numero = args.numero or base.get("numero") or "185"

    filtro: Optional[Set[str]] = None
    if args.somente.strip():
        filtro = {_norm_nome_bloco(x) for x in args.somente.split(",") if x.strip()}

    nomes = [str(b.get("nome") or "").strip() for b in (base.get("blocos") or [])]
    nomes = [n for n in nomes if n]
    if filtro:
        nomes = [n for n in nomes if _norm_nome_bloco(n) in filtro]

    pasta = Path(args.pasta_anexos) if args.pasta_anexos else Path()
    if not pasta.exists():
        # Fallback: pasta tipada pelo nome do condomínio no OneDrive CDOI
        nome_condo = str(base.get("nome_condominio") or "").strip()
        cep = re.sub(r"\D", "", str(base.get("cep") or ""))
        root = Path(r"C:\Users\rogge\OneDrive - Parceiros Oi\CDOI_Record_Vertical")
        if nome_condo and root.exists():
            candidatos = [
                p for p in root.iterdir()
                if p.is_dir() and nome_condo.upper() in p.name.upper()
            ]
            if cep:
                por_cep = [p for p in candidatos if cep[:5] in p.name.replace("-", "")]
                if por_cep:
                    candidatos = por_cep
            if candidatos:
                pasta = candidatos[0]
    carta = fachada = ""
    if not args.sem_anexos and pasta.exists():
        print(f"Pasta anexos: {pasta}")
        c = (
            list(pasta.glob("CARTA*.jfif"))
            + list(pasta.glob("CARTA*.jpg"))
            + list(pasta.glob("CARTA*.jpeg"))
            + list(pasta.glob("CARTA*.png"))
            + list(pasta.glob("CARTA*.PNG"))
        )
        f = (
            list(pasta.glob("FACHADA*.jfif"))
            + list(pasta.glob("FACHADA*.jpg"))
            + list(pasta.glob("FACHADA*.jpeg"))
            + list(pasta.glob("FACHADA*.png"))
            + list(pasta.glob("FACHADA*.PNG"))
        )
        carta = str(c[0]) if c else ""
        fachada = str(f[0]) if f else ""
        print(f"  carta={carta or '(não achou)'}")
        print(f"  fachada={fachada or '(não achou)'}")
    if not carta:
        carta = str(base.get("link_carta") or "")
    if not fachada:
        fachada = str(base.get("link_fachada") or "")

    resultados: List[Dict[str, Any]] = []
    print("Blocos alvo:", nomes)

    # Resolve IDs do banco antes de abrir browser
    ids_banco = {
        n: _resolver_obra_id(cdoi_id=cdoi_id, nome=n, lista={}) for n in nomes
    }
    com_id = [n for n in nomes if ids_banco.get(n)]
    sem_id = [n for n in nomes if not ids_banco.get(n)]
    print("Com obra_id no banco:", {n: ids_banco[n] for n in com_id})
    print("Sem obra_id (precisam da lista):", sem_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=35)
        context = browser.new_context(
            storage_state=_storage_state_path(),
            locale="pt-BR",
        )
        page = context.new_page()
        lista_obras: Dict[str, str] = {}

        svc = VtopSmartRiserService()
        svc.playwright = p
        svc.browser = browser
        svc.context = context
        svc.page = page

        def _ctx_dialog(dialog) -> None:
            try:
                dialog.accept()
            except Exception:
                pass

        context.on("dialog", _ctx_dialog)
        svc._dialog_via_context = True

        # Se precisar criar/descobrir, tenta Brownfield; senão só valida sessão
        brownfield_ok = False
        if sem_id:
            brownfield_ok = _abrir_brownfield(page, obrigatorio=False)
            if brownfield_ok:
                # Inventário paginado (mesma lógica do serviço)
                mapa_det = svc._listar_obras_endereco(logradouro, numero)
                lista_obras = {}
                for chave, items in (mapa_det or {}).items():
                    if not items:
                        continue
                    melhor = sorted(
                        items, key=lambda x: int(str(x.get("id") or "0") or 0)
                    )[0]
                    lista_obras[chave] = str(melhor["id"])
                    comp = str(melhor.get("complemento") or "").strip()
                    if comp:
                        lista_obras[_norm_nome_bloco(comp)] = str(melhor["id"])
                print("Obras na lista:", sorted(lista_obras.items()))
                Path(BASE / f"tmp_vtop_lista_cdoi_{cdoi_id}.json").write_text(
                    json.dumps(mapa_det, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                for nome_comp, oid in lista_obras.items():
                    persistir_vtop_obra_bloco(cdoi_id, nome_comp, oid)
                for n in list(sem_id):
                    oid = _resolver_obra_id(cdoi_id=cdoi_id, nome=n, lista=lista_obras)
                    if oid:
                        ids_banco[n] = oid
                sem_id = [n for n in nomes if not ids_banco.get(n)]
                print("Ainda sem ID após lista:", sem_id)
            else:
                print(
                    "AVISO: grade Brownfield indisponível. "
                    "Só processarei blocos com obra_id no banco."
                )
                if sem_id:
                    print("Pulando (sem ID e sem lista):", sem_id)
        else:
            _garantir_smartriser_sessao(page)

        print("A criar (não existem):", sem_id)
        print("A concluir (já existem):", [n for n in nomes if ids_banco.get(n)])

        for nome in nomes:
            print(f"\n======== {nome} ========")
            obra_id = ids_banco.get(nome) or _resolver_obra_id(
                cdoi_id=cdoi_id, nome=nome, lista=lista_obras
            )
            if not obra_id and nome in sem_id and not brownfield_ok:
                resultados.append(
                    {
                        "bloco": nome,
                        "ok": False,
                        "erro": "Sem obra_id e Brownfield indisponível (anti-duplicação).",
                    }
                )
                print("[SKIP]", resultados[-1]["erro"])
                continue

            try:
                _fechar_abas_extras(context, svc)
                page = svc.page

                payload = payload_para_bloco(base, nome)
                payload["cdoi_id"] = cdoi_id
                payload["salvar_coords"] = True
                if not args.sem_anexos:
                    payload["com_anexos"] = True
                    payload["anexar_arquivos"] = True
                    payload["link_carta"] = carta
                    payload["link_fachada"] = fachada
                else:
                    payload["link_carta"] = ""
                    payload["link_fachada"] = ""

                svc._payload_atual = dict(payload)
                keep_dialog = getattr(svc, "_dialog_via_context", False)
                svc.state.extras = {}
                svc._dialog_via_context = keep_dialog

                print(
                    f"UMS={payload['total_hps']} prevenda={payload['pre_venda']} "
                    f"({calcular_pre_venda_bloco(payload['total_hps'])}) obra_id={obra_id or 'NOVA'}"
                )

                if obra_id:
                    payload["obra_id"] = obra_id
                    svc._passo_abrir_obra_existente(obra_id)
                    svc._passo_concluir_cadastro_se_preciso(payload)
                    extras = dict(svc.state.extras)
                    ok_item = {
                        "bloco": nome,
                        "ok": True,
                        "obra_id": extras.get("obra_id") or obra_id,
                        "pre_venda": payload.get("pre_venda"),
                        "total_hps": payload.get("total_hps"),
                        "etapa": extras.get("obra_etapa_apos_validar")
                        or extras.get("obra_etapa_antes"),
                        "anexos_ok": list(extras.get("anexos_ok") or []),
                        "anexos_pulados": list(extras.get("anexos_pulados") or []),
                        "reaberta": True,
                        "ja_avancada": bool(
                            (extras.get("obra_etapa_antes") or 0) >= 2
                        ),
                    }
                    print("OK:", ok_item)
                    resultados.append(ok_item)
                    _fechar_abas_extras(context, svc)
                    continue
                else:
                    # Anti-duplicação: criar só com env + flag + lista confirmando ausência
                    from crm_app.services_vtop_smartriser import vtop_criar_permitido

                    payload["permitir_criar"] = not bool(args.nao_criar)
                    if not vtop_criar_permitido(payload):
                        raise RuntimeError(
                            "Sem obra_id e criação bloqueada (--nao-criar ou env)."
                        )
                    if not brownfield_ok:
                        raise RuntimeError(
                            "Inventário indisponível — não é seguro criar."
                        )
                    if _lista_tem_bloco(lista_obras, nome):
                        # Deveria ter resolvido ID acima; aborta em vez de duplicar
                        raise RuntimeError(
                            f"Bloco {nome} já está na lista mas sem ID resolvido — abortando criar."
                        )
                    if page.locator("#addUmaObra").count() == 0:
                        if not _abrir_brownfield(page, obrigatorio=False):
                            raise RuntimeError("Não abriu Brownfield para criar obra.")
                    print(
                        f"Criando obra nova '{nome}' "
                        f"(inventário confirmou ausência do complemento)"
                    )
                    svc._passo_abrir_modal_obra()
                    svc._passo_preencher_obra(payload, salvar=False)
                    svc._passo_coordenadas(payload, salvar=True)
                    lista = svc.page
                    with lista.expect_popup(timeout=60_000) as popinfo:
                        lista.locator("#b_criar_obra").click()
                    obra_page = popinfo.value
                    obra_page.wait_for_load_state("domcontentloaded")
                    svc.page = obra_page
                    obra_page.locator("#btn_salvarEtapa").wait_for(state="attached", timeout=60_000)
                    obra_page.locator(".item_checklist").first.wait_for(
                        state="visible", timeout=60_000
                    )
                    obra_id = svc._detectar_obra_id()
                    svc.state.extras["obra_id"] = obra_id
                    svc._gravar_vinculo_obra(str(obra_id))
                    ids_banco[nome] = str(obra_id)
                    print(f"obra_id criada={obra_id}")

                svc._passo_cadastro(payload)
                svc._passo_salvar_disquete()
                if not args.sem_validar:
                    svc._passo_validar()

                extras = dict(svc.state.extras)
                ok_item = {
                    "bloco": nome,
                    "ok": True,
                    "obra_id": extras.get("obra_id") or obra_id,
                    "pre_venda": payload.get("pre_venda"),
                    "total_hps": payload.get("total_hps"),
                    "etapa": extras.get("obra_etapa_apos_validar"),
                    "anexos_ok": list(extras.get("anexos_ok") or []),
                    "anexos_pulados": list(extras.get("anexos_pulados") or []),
                    "reaberta": bool(payload.get("obra_id")),
                }
                print("OK:", ok_item)
                resultados.append(ok_item)
                _fechar_abas_extras(context, svc)

            except Exception as exc:
                print(f"[ERRO] {nome}: {exc}")
                resultados.append({"bloco": nome, "ok": False, "erro": str(exc)})
                try:
                    _fechar_abas_extras(context, svc)
                except Exception as exc2:
                    print("Falha ao recuperar:", exc2)
                    break

        out = BASE / f"tmp_vtop_resultado_cdoi_{cdoi_id}.json"
        prev: List[Dict[str, Any]] = []
        if out.exists():
            try:
                prev = json.loads(out.read_text(encoding="utf-8"))
            except Exception:
                prev = []
        nomes_ok = {_norm_nome_bloco(r["bloco"]) for r in resultados if r.get("ok")}
        merged = [
            r for r in prev
            if _norm_nome_bloco(str(r.get("bloco") or "")) not in nomes_ok
        ]
        merged.extend(resultados)
        out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        # Compat: também espelha no caminho legado se for o default histórico
        legado = BASE / "tmp_vtop_resultado_lancar_restantes.json"
        if cdoi_id == 20:
            legado.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        context.storage_state(path=_storage_state_path())
        print("\nResultado:", out)
        time.sleep(2)
        browser.close()

    ok = sum(1 for r in resultados if r.get("ok"))
    print(f"Concluído: {ok}/{len(nomes)}")
    return 0 if ok == len(nomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
