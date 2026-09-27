#!/usr/bin/env python3
"""
Copia cadastros de Governança do site-record (schema public) para nova-velox.

1) Permissões dos Groups Django (auth_group + auth_group_permissions),
   casando Permission por (app_label, model, codename) — não por ID.
2) FormaPagamento, StatusCRM, MotivoPendencia.

Uso:
  railway run python ferramentas/sync_cadastros_site_record_para_nova_velox.py --dry-run
  railway run python ferramentas/sync_cadastros_site_record_para_nova_velox.py --apply

Não apaga registros existentes no destino; só upsert / sincroniza M2M de permissões.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any

import dj_database_url
import psycopg2
import psycopg2.extras

SRC = "public"
DST = "nova_velox"

# Perfis de acesso da Governança
GROUPS_SYNC = ("Vendedor", "Diretoria", "Supervisor", "BackOffice", "Admin")

# No site-record alguns models viviam no app legado "cadastros";
# no nova-velox estão em crm_app. Mapeia app_label na hora de casar Permission.
APP_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "cadastros": ("crm_app", "cadastros"),
    "crm_app": ("crm_app",),
}


def _load_database_url() -> str:
    url = (
        os.environ.get("DATABASE_UNPOOLED_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if url:
        return url
    out = subprocess.check_output(
        ["railway", "variables", "--kv"],
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    unpooled = ""
    pooled = ""
    for line in out.splitlines():
        if line.startswith("DATABASE_UNPOOLED_URL="):
            unpooled = line.split("=", 1)[1].strip()
        elif line.startswith("DATABASE_URL="):
            pooled = line.split("=", 1)[1].strip()
    url = unpooled or pooled
    if not url:
        raise SystemExit("DATABASE_URL não encontrada (env ou railway variables).")
    return url


def connect() -> Any:
    cfg = dj_database_url.parse(_load_database_url())
    return psycopg2.connect(
        host=cfg["HOST"],
        port=cfg.get("PORT") or 5432,
        dbname=cfg["NAME"],
        user=cfg["USER"],
        password=cfg["PASSWORD"],
        sslmode="require",
        options=f"-c search_path={DST},public",
    )


def fetchall(cur: Any, sql: str, params: tuple | list | None = None) -> list[tuple]:
    cur.execute(sql, params or ())
    return list(cur.fetchall())


def print_counts(cur: Any) -> None:
    print("=== Contagens atuais ===")
    for schema, label in ((SRC, "site-record"), (DST, "nova-velox")):
        cur.execute(
            f"""
            SELECT g.name, COUNT(gp.permission_id)
            FROM {schema}.auth_group g
            LEFT JOIN {schema}.auth_group_permissions gp ON gp.group_id = g.id
            GROUP BY g.name
            ORDER BY g.name
            """
        )
        print(f"[{label}] groups:")
        for name, cnt in cur.fetchall():
            print(f"  {name}: {cnt} perms")
        for table, title in (
            ("crm_forma_pagamento", "FormaPagamento"),
            ("crm_status", "StatusCRM"),
            ("crm_motivo_pendencia", "MotivoPendencia"),
        ):
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            print(f"[{label}] {title}: {cur.fetchone()[0]}")
    print()


def sync_formas_pagamento(cur: Any, apply: bool) -> int:
    rows = fetchall(
        cur,
        f"SELECT nome, ativo, aplica_desconto FROM {SRC}.crm_forma_pagamento ORDER BY nome",
    )
    n = 0
    for nome, ativo, aplica_desconto in rows:
        if apply:
            cur.execute(
                f"""
                INSERT INTO {DST}.crm_forma_pagamento (nome, ativo, aplica_desconto)
                VALUES (%s, %s, %s)
                ON CONFLICT (nome) DO UPDATE SET
                    ativo = EXCLUDED.ativo,
                    aplica_desconto = EXCLUDED.aplica_desconto
                """,
                (nome, ativo, aplica_desconto),
            )
        n += 1
    print(f"FormaPagamento: {n} registros {'upsert' if apply else 'a sincronizar'}")
    return n


def sync_status(cur: Any, apply: bool) -> int:
    rows = fetchall(
        cur,
        f"SELECT nome, tipo, estado, cor FROM {SRC}.crm_status ORDER BY tipo, nome",
    )
    n = 0
    for nome, tipo, estado, cor in rows:
        if apply:
            cur.execute(
                f"""
                INSERT INTO {DST}.crm_status (nome, tipo, estado, cor)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (nome, tipo) DO UPDATE SET
                    estado = EXCLUDED.estado,
                    cor = EXCLUDED.cor
                """,
                (nome, tipo, estado, cor or "#FFFFFF"),
            )
        n += 1
    print(f"StatusCRM: {n} registros {'upsert' if apply else 'a sincronizar'}")
    return n


def sync_motivos_pendencia(cur: Any, apply: bool) -> int:
    rows = fetchall(
        cur,
        f"""
        SELECT nome, tipo_pendencia
        FROM {SRC}.crm_motivo_pendencia
        ORDER BY tipo_pendencia, nome
        """,
    )
    # destino não tem unique(nome,tipo) necessariamente — upsert manual
    existing = {
        (r[0], r[1]): r[2]
        for r in fetchall(
            cur,
            f"SELECT nome, tipo_pendencia, id FROM {DST}.crm_motivo_pendencia",
        )
    }
    n_ins = n_upd = 0
    for nome, tipo in rows:
        key = (nome, tipo)
        if key in existing:
            n_upd += 1
            continue
        if apply:
            cur.execute(
                f"""
                INSERT INTO {DST}.crm_motivo_pendencia (nome, tipo_pendencia)
                VALUES (%s, %s)
                """,
                (nome, tipo),
            )
        n_ins += 1
    print(
        f"MotivoPendencia: {n_ins} novos, {n_upd} já existiam "
        f"({'inseridos' if apply else 'a inserir'})"
    )
    return n_ins + n_upd


def sync_group_permissions(cur: Any, apply: bool) -> None:
    """Espelha permissões dos Groups do site-record no nova-velox."""
    src_groups = fetchall(
        cur,
        f"SELECT id, name FROM {SRC}.auth_group WHERE name = ANY(%s) ORDER BY name",
        (list(GROUPS_SYNC),),
    )
    for src_gid, name in src_groups:
        cur.execute(
            f"SELECT id FROM {DST}.auth_group WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()
        if not row:
            if apply:
                cur.execute(
                    f"INSERT INTO {DST}.auth_group (name) VALUES (%s) RETURNING id",
                    (name,),
                )
                dst_gid = cur.fetchone()[0]
                print(f"Group '{name}': criado no destino (id={dst_gid})")
            else:
                print(f"Group '{name}': NÃO existe no destino (seria criado)")
                continue
        else:
            dst_gid = row[0]

        # Permissões do grupo origem, identificadas por app_label/model/codename
        perms = fetchall(
            cur,
            f"""
            SELECT ct.app_label, ct.model, p.codename
            FROM {SRC}.auth_group_permissions gp
            JOIN {SRC}.auth_permission p ON p.id = gp.permission_id
            JOIN {SRC}.django_content_type ct ON ct.id = p.content_type_id
            WHERE gp.group_id = %s
            ORDER BY 1, 2, 3
            """,
            (src_gid,),
        )

        # Resolve IDs no destino (com alias de app_label cadastros -> crm_app)
        dst_perm_ids: list[int] = []
        missing = 0
        for app_label, model, codename in perms:
            labels = APP_LABEL_ALIASES.get(app_label, (app_label,))
            found = None
            for label in labels:
                cur.execute(
                    f"""
                    SELECT p.id
                    FROM {DST}.auth_permission p
                    JOIN {DST}.django_content_type ct ON ct.id = p.content_type_id
                    WHERE ct.app_label = %s AND ct.model = %s AND p.codename = %s
                    """,
                    (label, model, codename),
                )
                found = cur.fetchone()
                if found:
                    break
            if found:
                dst_perm_ids.append(found[0])
            else:
                missing += 1

        # Dedup
        dst_perm_ids = list(dict.fromkeys(dst_perm_ids))

        if apply:
            cur.execute(
                f"DELETE FROM {DST}.auth_group_permissions WHERE group_id = %s",
                (dst_gid,),
            )
            for pid in dst_perm_ids:
                cur.execute(
                    f"""
                    INSERT INTO {DST}.auth_group_permissions (group_id, permission_id)
                    VALUES (%s, %s)
                    """,
                    (dst_gid, pid),
                )

        print(
            f"Group '{name}': {len(perms)} perms origem -> "
            f"{len(dst_perm_ids)} mapeadas, {missing} sem match no destino"
            + (" [aplicado]" if apply else " [dry-run]")
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Só mostra o que faria")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica no schema nova_velox (produção)",
    )
    parser.add_argument(
        "--skip-groups",
        action="store_true",
        help="Não sincroniza permissões de Groups",
    )
    parser.add_argument(
        "--skip-cadastros",
        action="store_true",
        help="Não sincroniza FormaPagamento/Status/Pendências",
    )
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        print("Use --dry-run ou --apply.", file=sys.stderr)
        return 1
    if args.dry_run and args.apply:
        print("Escolha só um: --dry-run ou --apply.", file=sys.stderr)
        return 1

    apply = bool(args.apply)
    conn = connect()
    try:
        cur = conn.cursor()
        print_counts(cur)

        if not args.skip_cadastros:
            sync_formas_pagamento(cur, apply)
            sync_status(cur, apply)
            sync_motivos_pendencia(cur, apply)

        if not args.skip_groups:
            sync_group_permissions(cur, apply)

        if apply:
            conn.commit()
            print("\nCOMMIT ok.")
            print_counts(cur)
        else:
            conn.rollback()
            print("\nDry-run: nenhuma alteração gravada.")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
