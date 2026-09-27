"""Vincula vendedor nas vendas legado (LOGIN=TT → matricula_pap) e reporta status."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg2

RAILWAY = r"C:\Users\rogge\AppData\Roaming\npm\railway.cmd"
XLSX = Path(r"C:\site-gm\exports\legado_pap\Legado_GM_TELECOM_AbrAgo26_INSTALADAS.xlsx")
PORT = 15555


def main():
    os.chdir(r"C:\site-gm")
    d = json.loads(
        subprocess.run(
            [RAILWAY, "variable", "list", "--service", "site-gm", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )
    raw = d.get("DATABASE_UNPOOLED_URL") or d["DATABASE_URL"]
    proc = subprocess.Popen(
        [RAILWAY, "connect", "Postgres", "--tunnel-only", "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while True:
        line = proc.stdout.readline()
        if line and str(PORT) in line:
            break
        if proc.poll() is not None:
            raise SystemExit("túnel falhou")
    for _ in range(40):
        try:
            socket.create_connection(("127.0.0.1", PORT), 1).close()
            break
        except OSError:
            time.sleep(0.2)
    time.sleep(1)

    p = urlparse(raw)
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=PORT,
        user=p.username,
        password=p.password,
        dbname=(p.path or "/railway").lstrip("/"),
    )
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO gm, public")

    # status
    cur.execute(
        """
        SELECT s.nome, count(*)
        FROM crm_venda v
        LEFT JOIN crm_status s ON s.id = v.status_tratamento_id
        WHERE v.observacoes ILIKE %s
        GROUP BY 1 ORDER BY 2 DESC
        """,
        ("%LEGADO%",),
    )
    print("tratamento:", cur.fetchall())
    cur.execute(
        """
        SELECT s.nome, s.estado, count(*)
        FROM crm_venda v
        LEFT JOIN crm_status s ON s.id = v.status_esteira_id
        WHERE v.observacoes ILIKE %s
        GROUP BY 1,2 ORDER BY 3 DESC
        """,
        ("%LEGADO%",),
    )
    print("esteira:", cur.fetchall())

    # mapa matricula -> user
    cur.execute(
        """
        SELECT id, username, upper(trim(matricula_pap))
        FROM usuarios_usuario
        WHERE matricula_pap IS NOT NULL AND trim(matricula_pap) <> ''
        """
    )
    mat_map = {}
    for uid, uname, mat in cur.fetchall():
        mat_map[mat] = (uid, uname)
    print("usuarios com matricula_pap:", len(mat_map))

    df = pd.read_excel(XLSX, dtype=str)
    df.columns = [str(c).strip().upper() for c in df.columns]
    print("linhas planilha", len(df))

    updated = 0
    missing_user = {}
    missing_venda = 0
    already = 0

    for _, row in df.iterrows():
        os_raw = str(row.get("OS") or "").strip()
        if os_raw.endswith(".0"):
            os_raw = os_raw[:-2]
        login = str(row.get("LOGIN_VENDEDOR") or "").strip().upper()
        if not os_raw or not login:
            continue
        user = mat_map.get(login)
        if not user:
            missing_user[login] = missing_user.get(login, 0) + 1
            continue
        uid, _ = user
        cur.execute(
            """
            SELECT id, vendedor_id FROM crm_venda
            WHERE observacoes ILIKE %s
              AND (
                ordem_servico = %s
                OR ltrim(ordem_servico, '0') = ltrim(%s, '0')
              )
            """,
            ("%LEGADO%", os_raw, os_raw),
        )
        hits = cur.fetchall()
        if not hits:
            missing_venda += 1
            continue
        for vid, vend in hits:
            if vend == uid:
                already += 1
                continue
            cur.execute(
                "UPDATE crm_venda SET vendedor_id=%s WHERE id=%s",
                (uid, vid),
            )
            updated += 1

    conn.commit()
    print("updated", updated, "already", already, "missing_venda", missing_venda)
    print("missing_user top", sorted(missing_user.items(), key=lambda x: -x[1])[:20])

    cur.execute(
        """
        SELECT count(*) FILTER (WHERE vendedor_id IS NULL),
               count(*) FILTER (WHERE vendedor_id IS NOT NULL)
        FROM crm_venda WHERE observacoes ILIKE %s
        """,
        ("%LEGADO%",),
    )
    print("legado sem/com vendedor", cur.fetchone())

    # simula filtro esteira abril
    cur.execute(
        """
        SELECT count(*)
        FROM crm_venda v
        JOIN crm_status st ON st.id = v.status_tratamento_id
        WHERE v.ativo
          AND v.vendedor_id IS NOT NULL
          AND v.ordem_servico IS NOT NULL AND v.ordem_servico <> ''
          AND upper(st.nome)='CADASTRADA'
          AND v.data_abertura::date >= '2026-04-01'
          AND v.data_abertura::date <= '2026-04-30'
        """
    )
    print("abril com filtro esteira", cur.fetchone()[0])
    cur.execute(
        """
        SELECT date_trunc('month', v.data_abertura)::date, count(*)
        FROM crm_venda v
        JOIN crm_status st ON st.id = v.status_tratamento_id
        WHERE v.ativo
          AND v.vendedor_id IS NOT NULL
          AND v.ordem_servico IS NOT NULL AND v.ordem_servico <> ''
          AND upper(st.nome)='CADASTRADA'
          AND v.data_abertura::date >= '2026-04-01'
          AND v.data_abertura::date < '2026-09-01'
        GROUP BY 1 ORDER BY 1
        """
    )
    print("abr-ago com filtro", cur.fetchall())

    proc.terminate()


if __name__ == "__main__":
    main()
