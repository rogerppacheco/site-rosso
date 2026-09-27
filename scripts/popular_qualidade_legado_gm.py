"""Popula SafraM10/ContratoM10 para legado — rápido (signals desligados)."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

BASE = Path(__file__).resolve().parents[1]
RAILWAY = Path(os.environ.get("APPDATA", "")) / "npm" / "railway.cmd"
RAILWAY = str(RAILWAY) if RAILWAY.exists() else "railway"
PORT = 15562
MESES = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]


def _tunnel_and_env():
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
    dburl = urlunparse(
        (
            "postgresql",
            f"{p.username}:{quote(p.password or '', safe='')}@127.0.0.1:{PORT}",
            p.path or "/railway",
            "",
            "",
            "",
        )
    )
    os.environ["DATABASE_URL"] = dburl
    os.environ["POSTGRES_SCHEMA"] = "gm"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
    return proc


def main():
    proc = _tunnel_and_env()
    sys.path.insert(0, str(BASE))
    import django

    django.setup()

    from django.db.models import Q
    from django.db.models.signals import post_save

    from crm_app.models import ContratoM10, SafraM10, Venda
    from crm_app import signals_m10_automacao as sig
    from crm_app import signals as crm_signals
    from crm_app.views import _recalcular_totais_safra_m10

    # Evita sync FPD/faturas por contrato (muito lento em lote)
    post_save.disconnect(sig.sincronizar_contrato_m10_com_fpd, sender=ContratoM10)
    post_save.disconnect(crm_signals.criar_faturas_automatico, sender=ContratoM10)
    post_save.disconnect(sig.criar_contrato_m10_automatico, sender=Venda)

    print("contratos antes", ContratoM10.objects.count())

    legado = Q(observacoes__icontains="LEGADO")
    total_criados = 0
    for mes_ref in MESES:
        y, m = map(int, mes_ref.split("-"))
        data_inicio = date(y, m, 1)
        data_fim = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)

        safra, _ = SafraM10.objects.get_or_create(
            mes_referencia=data_inicio,
            defaults={
                "total_instalados": 0,
                "total_ativos": 0,
                "total_elegivel_bonus": 0,
                "valor_bonus_total": 0,
            },
        )

        vendas = list(
            Venda.objects.filter(
                legado,
                data_instalacao__gte=data_inicio,
                data_instalacao__lt=data_fim,
                data_instalacao__isnull=False,
                ativo=True,
                status_esteira__nome__iexact="INSTALADA",
            )
            .exclude(ordem_servico__isnull=True)
            .exclude(ordem_servico="")
            .select_related("cliente", "vendedor", "plano")
            .order_by("id")
        )

        existentes = set(
            ContratoM10.objects.filter(
                ordem_servico__in=[v.ordem_servico for v in vendas]
            ).values_list("ordem_servico", flat=True)
        )

        batch = []
        for venda in vendas:
            if venda.ordem_servico in existentes:
                continue
            batch.append(
                ContratoM10(
                    safra=mes_ref,
                    venda=venda,
                    numero_contrato=venda.ordem_servico,
                    ordem_servico=venda.ordem_servico,
                    cliente_nome=venda.cliente.nome_razao_social if venda.cliente else "N/D",
                    cpf_cliente=venda.cliente.cpf_cnpj if venda.cliente else "",
                    vendedor=venda.vendedor,
                    data_instalacao=venda.data_instalacao,
                    plano_original=venda.plano.nome if venda.plano else "N/D",
                    plano_atual=venda.plano.nome if venda.plano else "N/D",
                    valor_plano=(getattr(venda.plano, "valor", 0) or 0) if venda.plano else 0,
                    status_contrato="ATIVO",
                    elegivel_bonus=False,
                    observacao=f"Importado de Venda legado #{venda.id}",
                )
            )
            existentes.add(venda.ordem_servico)

        if batch:
            ContratoM10.objects.bulk_create(batch, batch_size=200)
        criados = len(batch)
        total_criados += criados

        # Atualiza vendedor em contratos já criados sem vendedor
        for venda in vendas:
            if venda.vendedor_id:
                ContratoM10.objects.filter(
                    ordem_servico=venda.ordem_servico, vendedor__isnull=True
                ).update(vendedor_id=venda.vendedor_id, venda_id=venda.id)

        total = ContratoM10.objects.filter(
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
        ).count()
        ativos = ContratoM10.objects.filter(
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
            status_contrato="ATIVO",
        ).count()
        safra.total_instalados = total
        safra.total_ativos = ativos
        safra.save(update_fields=["total_instalados", "total_ativos"])
        try:
            _recalcular_totais_safra_m10(mes_ref)
        except Exception as exc:
            print(mes_ref, "recalc:", type(exc).__name__, exc)
        print(f"{mes_ref}: vendas={len(vendas)} criados={criados} total_safra={total}")

    # Sync FPD rápido em lote (sem criar 10 faturas por contrato no signal pesado)
    from crm_app.models import ImportacaoFPD
    from django.utils import timezone

    linked = 0
    qs = ContratoM10.objects.filter(observacao__icontains="legado").filter(
        Q(numero_contrato_definitivo__isnull=True) | Q(numero_contrato_definitivo="")
    )
    # mapa OS -> fpd
    fps = ImportacaoFPD.objects.exclude(nr_ordem__isnull=True).exclude(nr_ordem="")
    by_os = {}
    for f in fps.only(
        "id", "nr_ordem", "numero_os", "id_contrato", "dt_venc_orig", "dt_pagamento",
        "ds_status_fatura", "vl_fatura", "nr_dias_atraso", "contrato_m10_id",
    ).iterator(chunk_size=2000):
        if f.nr_ordem:
            by_os.setdefault(str(f.nr_ordem).lstrip("0") or f.nr_ordem, f)
            by_os.setdefault(str(f.nr_ordem), f)
        if getattr(f, "numero_os", None):
            by_os.setdefault(str(f.numero_os).lstrip("0") or str(f.numero_os), f)

    now = timezone.now()
    for c in qs.iterator(chunk_size=200):
        key = str(c.ordem_servico or "")
        fpd = by_os.get(key) or by_os.get(key.lstrip("0") or key)
        if not fpd or not fpd.id_contrato:
            continue
        ContratoM10.objects.filter(pk=c.id).update(
            numero_contrato_definitivo=fpd.id_contrato,
            data_vencimento_fpd=fpd.dt_venc_orig,
            data_pagamento_fpd=fpd.dt_pagamento,
            status_fatura_fpd=fpd.ds_status_fatura,
            valor_fatura_fpd=fpd.vl_fatura,
            nr_dias_atraso_fpd=fpd.nr_dias_atraso,
            data_ultima_sincronizacao_fpd=now,
        )
        if not fpd.contrato_m10_id:
            ImportacaoFPD.objects.filter(pk=fpd.id, contrato_m10__isnull=True).update(
                contrato_m10_id=c.id
            )
        linked += 1

    print("FPD vinculados", linked)

    # Gera faturas M-10 (necessário p/ colunas na Qualidade)
    print("Gerando faturas...")
    n_fat = 0
    for c in ContratoM10.objects.filter(observacao__icontains="legado").iterator(chunk_size=100):
        if not c.data_instalacao:
            continue
        try:
            c.criar_ou_atualizar_faturas()
            n_fat += 1
        except Exception as exc:
            print("fatura fail", c.ordem_servico, type(exc).__name__, exc)
        if n_fat and n_fat % 50 == 0:
            print("  faturas ok", n_fat)
    print("faturas processadas", n_fat)
    print("contratos depois", ContratoM10.objects.count())
    print(
        "safras",
        list(
            SafraM10.objects.order_by("mes_referencia").values_list(
                "mes_referencia", "total_instalados"
            )
        ),
    )
    proc.terminate()


if __name__ == "__main__":
    main()
