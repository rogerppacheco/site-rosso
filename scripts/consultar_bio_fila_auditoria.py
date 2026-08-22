"""
Lista vendas pendentes na auditoria (produção) e consulta biometria no Br Pronto.

Uso:
  python scripts/consultar_bio_fila_auditoria.py              # só lista
  python scripts/consultar_bio_fila_auditoria.py --consultar  # lista + consulta Br Pronto
  python scripts/consultar_bio_fila_auditoria.py --consultar --limite 5 --headless
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _prod_database_url() -> str:
    """Obtém DATABASE_URL de produção (env PROD_DATABASE_URL ou Railway CLI)."""
    env_url = os.environ.get("PROD_DATABASE_URL") or os.environ.get("DATABASE_URL_PROD")
    if env_url:
        return env_url

    import json
    import subprocess

    # No Windows o `railway` é .cmd/.ps1 — preferir railway.cmd
    candidates = ["railway.cmd", "railway"]
    last_err = ""
    for cmd in candidates:
        r = subprocess.run(
            [cmd, "variables", "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            shell=(cmd.endswith(".cmd")),
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            url = data.get("DATABASE_UNPOOLED_URL") or data.get("DATABASE_URL")
            if url:
                return url
        last_err = r.stderr or r.stdout or f"exit {r.returncode}"
    raise SystemExit(f"railway variables falhou: {last_err}")


def _query_pendentes_prod(url: str, limite: int | None = None):
    import psycopg2
    import psycopg2.extras

    sql = """
        SELECT
            v.id,
            v.data_criacao,
            c.nome_razao_social AS cliente_nome,
            regexp_replace(COALESCE(c.cpf_cnpj, ''), '[^0-9]', '', 'g') AS cpf,
            regexp_replace(COALESCE(v.cpf_representante_legal, ''), '[^0-9]', '', 'g') AS cpf_repr,
            u.username AS vendedor,
            st.nome AS status_tratamento,
            st.estado AS status_estado
        FROM crm_venda v
        JOIN crm_cliente c ON c.id = v.cliente_id
        LEFT JOIN usuarios_usuario u ON u.id = v.vendedor_id
        LEFT JOIN crm_status st ON st.id = v.status_tratamento_id
        WHERE v.ativo = TRUE
          AND v.status_tratamento_id IS NOT NULL
          AND v.status_esteira_id IS NULL
          AND (st.estado IS NULL OR UPPER(st.estado) <> 'FECHADO')
        ORDER BY v.id DESC
    """
    if limite:
        sql += f" LIMIT {int(limite)}"

    conn = psycopg2.connect(url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return list(cur.fetchall())
    finally:
        conn.close()


def _cpf_consulta(row) -> str:
    cpf = (row.get("cpf") or "").strip()
    if len(cpf) == 11:
        return cpf
    repr_ = (row.get("cpf_repr") or "").strip()
    if len(repr_) == 11:
        return repr_
    return cpf if len(cpf) == 11 else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consultar", action="store_true", help="Consultar Br Pronto para cada CPF")
    parser.add_argument("--limite", type=int, default=0, help="Limitar quantidade (0 = todos)")
    parser.add_argument("--headless", action="store_true", help="Browser headless (padrão: visível)")
    parser.add_argument("--local", action="store_true", help="Usar banco LOCAL em vez de produção")
    args = parser.parse_args()

    if args.local:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
        import django

        django.setup()
        from crm_app.models import Venda

        qs = (
            Venda.objects.filter(ativo=True, status_tratamento__isnull=False, status_esteira__isnull=True)
            .exclude(status_tratamento__estado__iexact="FECHADO")
            .select_related("cliente", "vendedor", "status_tratamento")
            .order_by("-id")
        )
        if args.limite:
            qs = qs[: args.limite]
        rows = []
        for v in qs:
            rows.append(
                {
                    "id": v.id,
                    "data_criacao": v.data_criacao,
                    "cliente_nome": getattr(v.cliente, "nome", "") or "",
                    "cpf": re.sub(r"\D", "", getattr(v.cliente, "cpf_cnpj", "") or ""),
                    "cpf_repr": re.sub(r"\D", "", getattr(v, "cpf_representante_legal", "") or ""),
                    "vendedor": getattr(v.vendedor, "username", "") or "",
                    "status_tratamento": getattr(v.status_tratamento, "nome", "") or "",
                    "status_estado": getattr(v.status_tratamento, "estado", "") or "",
                }
            )
        fonte = "LOCAL"
    else:
        print("Conectando em PRODUÇÃO (somente leitura)...")
        url = _prod_database_url()
        rows = _query_pendentes_prod(url, limite=args.limite or None)
        fonte = "PRODUÇÃO"

    print(f"\n=== Fila auditoria ({fonte}): {len(rows)} venda(s) ===\n")
    cpfs_unicos = []
    seen = set()
    for r in rows:
        cpf = _cpf_consulta(r)
        dt = r.get("data_criacao")
        dt_s = dt.strftime("%d/%m/%Y %H:%M") if hasattr(dt, "strftime") else str(dt)
        print(
            f"#{r['id']} | {dt_s} | {r.get('cliente_nome','')[:30]:30} | "
            f"CPF={cpf or '-'} | {r.get('vendedor','')} | {r.get('status_tratamento','')}"
        )
        if cpf and cpf not in seen:
            seen.add(cpf)
            cpfs_unicos.append((r["id"], cpf, r.get("cliente_nome") or ""))

    print(f"\nCPFs únicos válidos: {len(cpfs_unicos)}")
    if not args.consultar:
        print("Use --consultar para rodar a biometria no Br Pronto.")
        return

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
    import django

    django.setup()
    from crm_app.pool_brpronto import obter_login_brpronto, liberar_login_brpronto
    from crm_app.services_brpronto import consultar_biometria_brpronto

    headless = args.headless
    print(f"\nConsultando Br Pronto (headless={headless})...\n")

    resultados = []
    for venda_id, cpf, nome in cpfs_unicos:
        lock = f"fila-audit:{venda_id}"
        bo, err = obter_login_brpronto(lock, origem="auditoria")
        if not bo:
            print(f"#{venda_id} CPF={cpf} SKIP pool: {err}")
            resultados.append((venda_id, cpf, nome, False, err or "pool", None))
            continue
        try:
            t0 = time.time()
            ok, msg, res = consultar_biometria_brpronto(
                login=bo.brpronto_login or "",
                senha=bo.brpronto_senha or "",
                cpf=cpf,
                dominio=bo.brpronto_dominio or "BrPronto",
                headless=headless,
                timeout_ms=90000,
            )
            elapsed = round(time.time() - t0, 1)
            if not ok:
                print(f"#{venda_id} CPF={cpf} ERRO ({elapsed}s): {msg}")
                resultados.append((venda_id, cpf, nome, False, msg, None))
            else:
                aprovada = bool(res.get("aprovada"))
                data = res.get("data_mais_recente_apta")
                n = len(res.get("registros") or [])
                status = "APROVADA" if aprovada else "NÃO APTA"
                print(
                    f"#{venda_id} CPF={cpf} {status} ({elapsed}s) "
                    f"regs={n} data_apta={data or '-'} | {nome[:25]}"
                )
                resultados.append((venda_id, cpf, nome, aprovada, None, data))
        finally:
            liberar_login_brpronto(bo.id, lock)
        time.sleep(1.5)

    aprovados = sum(1 for r in resultados if r[3] is True)
    erros = sum(1 for r in resultados if r[4])
    print(
        f"\n=== Resumo: {len(resultados)} CPFs | "
        f"aprovados={aprovados} | não aptos={len(resultados)-aprovados-erros} | erros={erros} ==="
    )


if __name__ == "__main__":
    main()
