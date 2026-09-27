"""Coleta Histórico PAP mês a mês e gera Excel(s) localmente (base legado).

Não grava vendas no CRM. Usa login PAP (matrícula/senha) do banco GM ou args.

Uso:
  python scripts/coletar_historico_pap_meses.py --ano 2026 --meses 5,6,7,8
  python scripts/coletar_historico_pap_meses.py --ano 2026 --meses 5,6,7,8 --headless
  python scripts/coletar_historico_pap_meses.py --matricula TT731913 --senha '***' --ano 2026
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse, urlunparse

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

OUT_DIR = BASE_DIR / "exports" / "legado_pap"


def _tunnel_db_and_creds(matricula_preferida: str = "TT731913"):
    """Abre túnel Railway e devolve (dburl, matricula, senha, username)."""
    import socket

    import psycopg2

    railway = Path(os.environ.get("APPDATA", "")) / "npm" / "railway.cmd"
    railway = str(railway) if railway.exists() else "railway"
    os.chdir(BASE_DIR)
    d = json.loads(
        subprocess.run(
            [railway, "variable", "list", "--service", "site-gm", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )
    raw = d.get("DATABASE_UNPOOLED_URL") or d["DATABASE_URL"]
    port = 15540
    proc = subprocess.Popen(
        [railway, "connect", "Postgres", "--tunnel-only", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while True:
        line = proc.stdout.readline()
        if line and str(port) in line:
            break
        if proc.poll() is not None:
            raise SystemExit("Falha ao abrir túnel Postgres")
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            break
        except OSError:
            time.sleep(0.2)
    time.sleep(1)
    p = urlparse(raw)
    dburl = urlunparse(
        (
            "postgresql",
            f"{p.username}:{quote(p.password or '', safe='')}@127.0.0.1:{port}",
            p.path or "/railway",
            "",
            "",
            "",
        )
    )
    conn = psycopg2.connect(dburl)
    cur = conn.cursor()
    cur.execute("SET search_path TO gm")
    cur.execute(
        """
        SELECT username, matricula_pap, senha_pap
        FROM usuarios_usuario
        WHERE is_active
          AND coalesce(matricula_pap,'') <> ''
          AND coalesce(senha_pap,'') <> ''
          AND matricula_pap ILIKE %s
        LIMIT 1
        """,
        (matricula_preferida,),
    )
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            SELECT username, matricula_pap, senha_pap
            FROM usuarios_usuario
            WHERE is_active
              AND coalesce(matricula_pap,'') <> ''
              AND coalesce(senha_pap,'') <> ''
            ORDER BY id
            LIMIT 1
            """
        )
        row = cur.fetchone()
    conn.close()
    if not row:
        proc.terminate()
        raise SystemExit("Nenhum usuário com matrícula/senha PAP no schema gm")
    return dburl, proc, row[1].strip(), row[2].strip(), row[0]


def _meses_periodo(ano: int, meses: list[int]) -> list[tuple[str, date, date]]:
    out = []
    for m in meses:
        ini = date(ano, m, 1)
        fim = date(ano, m, calendar.monthrange(ano, m)[1])
        out.append((f"{ano}-{m:02d}", ini, fim))
    return out


def _coletar_mes(page, data_inicio: date, data_fim: date, tipos: list[str]) -> list[dict]:
    from crm_app.historico_pap import extrair_lista_api, normalizar_pedido, normalizar_tipo
    from crm_app.historico_pap_service import _coletar_vendas_via_rede_spa

    itens: list[dict] = []
    vistos: set[str] = set()
    for tipo in tipos:
        packs = _coletar_vendas_via_rede_spa(
            page,
            data_inicio=data_inicio,
            data_fim=data_fim,
            timeout_ms=90000,
            max_paginas_ui=25,
            tipo_crm=tipo,
        )
        for pack in packs or []:
            lista, total = extrair_lista_api(pack.get("json"))
            tipo_url = ""
            try:
                qs = parse_qs(urlparse(pack.get("url") or "").query)
                tipo_url = ((qs.get("tipoVenda") or qs.get("tipovenda") or [""])[0] or "").upper()
            except Exception:
                tipo_url = ""
            print(f"    tipo={tipo} pacote +{len(lista or [])} (total_api={total})")
            for x in lista or []:
                if not isinstance(x, dict):
                    continue
                item = dict(x)
                if tipo_url and not (
                    item.get("tipoVenda") or item.get("tipo_venda") or item.get("tipo")
                ):
                    item["tipoVenda"] = tipo_url
                ped = normalizar_pedido(item.get("numeroPedido"))
                if not ped or ped in vistos:
                    continue
                vistos.add(ped)
                itens.append(item)
    return itens


def main():
    parser = argparse.ArgumentParser(description="Coleta Histórico PAP mês a mês → Excel local")
    parser.add_argument("--ano", type=int, default=2026)
    parser.add_argument("--meses", default="5,6,7,8", help="Lista CSV de meses, ex: 5,6,7,8")
    parser.add_argument("--matricula", default="")
    parser.add_argument("--senha", default="")
    parser.add_argument("--tipos", default="VENDA", help="VENDA ou VENDA,INTERESSE,PRE_VENDA")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--headed", action="store_true", help="Abrir navegador visível")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--consolidado", action="store_true", help="Também gera Excel único")
    parser.add_argument("--from-db", action="store_true", default=True, help="Credenciais do GM via túnel")
    args = parser.parse_args()

    meses = [int(x.strip()) for x in args.meses.split(",") if x.strip()]
    tipos = [t.strip().upper() for t in args.tipos.split(",") if t.strip()]
    headless = not args.headed
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tunnel_proc = None
    matricula = (args.matricula or "").strip()
    senha = (args.senha or "").strip()
    if (not matricula or not senha) and args.from_db:
        print("Abrindo túnel + lendo credenciais PAP do GM...")
        dburl, tunnel_proc, matricula, senha, uname = _tunnel_db_and_creds(
            matricula or "TT731913"
        )
        os.environ["DATABASE_URL"] = dburl
        os.environ["DATABASE_UNPOOLED_URL"] = dburl
        os.environ["POSTGRES_SCHEMA"] = "gm"
        print(f"Login PAP: {uname} / {matricula}")
    if not matricula or not senha:
        raise SystemExit("Informe --matricula/--senha ou use --from-db")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
    os.environ.setdefault("SECRET_KEY", "coletar-pap-local")
    import django

    django.setup()

    from crm_app.historico_pap import PAP_HISTORICO_URL, map_pedido_api, montar_xlsx_historico
    from crm_app.historico_pap_service import _coletar_vendas_via_rede_spa  # noqa: F401
    from crm_app.services_pap_nio import PAPNioAutomation

    periodos = _meses_periodo(args.ano, meses)
    print(f"Períodos: {[p[0] for p in periodos]} | tipos={tipos} | headless={headless}")
    print(f"Saída: {out_dir}")

    automacao = PAPNioAutomation(
        matricula_pap=matricula,
        senha_pap=senha,
        vendedor_nome="Coleta-Legado-PAP",
        headless=headless,
        capture_screenshots=False,
        optimize_for_credit=True,
        url_pos_login=PAP_HISTORICO_URL,
    )
    t0 = time.time()
    ok, msg = automacao.iniciar_sessao()
    if not ok:
        if tunnel_proc:
            tunnel_proc.terminate()
        raise SystemExit(f"Falha login PAP: {msg}")
    print(f"Sessão OK em {time.time() - t0:.1f}s")

    todos: list[dict] = []
    resumo = []
    try:
        for label, ini, fim in periodos:
            print(f"\n=== Coletando {label} ({ini} → {fim}) ===")
            t1 = time.time()
            itens = _coletar_mes(automacao.page, ini, fim, tipos)
            linhas = [map_pedido_api(it) for it in itens]
            blob = montar_xlsx_historico(linhas)
            path = out_dir / f"Historico_PAP_{label}.xlsx"
            path.write_bytes(blob)
            elapsed = time.time() - t1
            print(f"  → {path.name}: {len(linhas)} pedidos em {elapsed:.1f}s")
            resumo.append((label, len(linhas), str(path)))
            todos.extend(linhas)

        if args.consolidado or len(periodos) > 1:
            # dedupe por pedido
            seen = set()
            consol = []
            for r in todos:
                ped = str(r.get("pedido") or "")
                if not ped or ped in seen:
                    continue
                seen.add(ped)
                consol.append(r)
            nome = f"Historico_PAP_{args.ano}-{min(meses):02d}_{args.ano}-{max(meses):02d}.xlsx"
            path = out_dir / nome
            path.write_bytes(montar_xlsx_historico(consol))
            print(f"\nConsolidado: {path.name} ({len(consol)} pedidos únicos)")
            resumo.append(("consolidado", len(consol), str(path)))
    finally:
        try:
            automacao.encerrar_sessao()
        except Exception:
            pass
        if tunnel_proc:
            tunnel_proc.terminate()

    print("\n===== RESUMO =====")
    for label, n, p in resumo:
        print(f"  {label}: {n} → {p}")
    print(f"Total bruto linhas: {len(todos)}")


if __name__ == "__main__":
    main()
