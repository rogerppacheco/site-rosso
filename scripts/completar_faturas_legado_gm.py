"""Completa faturas M-10 faltantes — resiliente a queda do túnel."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

BASE = Path(__file__).resolve().parents[1]
RAILWAY = Path(os.environ.get("APPDATA", "")) / "npm" / "railway.cmd"
RAILWAY = str(RAILWAY) if RAILWAY.exists() else "railway"
PORT = 15580


def open_tunnel():
    os.chdir(BASE)
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
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), 1).close()
            break
        except OSError:
            time.sleep(0.2)
    time.sleep(1)
    p = urlparse(raw)
    os.environ["DATABASE_URL"] = urlunparse(
        (
            "postgresql",
            f"{p.username}:{quote(p.password or '', safe='')}@127.0.0.1:{PORT}",
            p.path or "/railway",
            "",
            "",
            "",
        )
    )
    os.environ["POSTGRES_SCHEMA"] = "gm"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
    return proc


def django_ready():
    sys.path.insert(0, str(BASE))
    import django
    from django.db import close_old_connections

    django.setup()
    close_old_connections()
    from django.db.models.signals import post_save
    from crm_app.models import ContratoM10
    from crm_app import signals as crm_signals
    from crm_app import signals_m10_automacao as sig

    post_save.disconnect(crm_signals.criar_faturas_automatico, sender=ContratoM10)
    post_save.disconnect(sig.sincronizar_contrato_m10_com_fpd, sender=ContratoM10)
    return ContratoM10


def ids_pendentes(ContratoM10):
    from django.db.models import Count

    return list(
        ContratoM10.objects.filter(observacao__icontains="legado", data_instalacao__isnull=False)
        .annotate(nfat=Count("faturas"))
        .filter(nfat__lt=10)
        .order_by("id")
        .values_list("id", flat=True)
    )


def main():
    proc = open_tunnel()
    ContratoM10 = django_ready()
    ids = ids_pendentes(ContratoM10)
    print("pendentes", len(ids))
    ok = fail = 0
    from django.db import close_old_connections, connection

    for i, cid in enumerate(ids, 1):
        try:
            close_old_connections()
            c = ContratoM10.objects.get(pk=cid)
            c.criar_ou_atualizar_faturas()
            ok += 1
        except Exception as exc:
            fail += 1
            print("fail", cid, type(exc).__name__, exc)
            # reconecta túnel se caiu
            if "Connection refused" in str(exc) or "closed" in str(exc).lower():
                try:
                    proc.terminate()
                except Exception:
                    pass
                time.sleep(2)
                proc = open_tunnel()
                ContratoM10 = django_ready()
                try:
                    connection.ensure_connection()
                    c = ContratoM10.objects.get(pk=cid)
                    c.criar_ou_atualizar_faturas()
                    ok += 1
                    fail -= 1
                    print("  retry ok", cid)
                except Exception as exc2:
                    print("  retry fail", cid, type(exc2).__name__, exc2)
        if i % 20 == 0:
            print(f"  {i}/{len(ids)} ok={ok} fail={fail}")
    print("fim ok", ok, "fail", fail, "restantes", len(ids_pendentes(ContratoM10)))
    try:
        proc.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
