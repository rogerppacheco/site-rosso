"""Lista reemissões contabilizadas em agosto/2026 (produção)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django

django.setup()

from datetime import date

from crm_app.models import Venda


def dump(titulo: str, qs) -> None:
    print(f"==== {titulo} count={qs.count()}", flush=True)
    print(
        "id|os|abertura|criacao|pedido|esteira|trat|vendedor|cliente",
        flush=True,
    )
    for v in qs:
        cli = (v.cliente.nome_razao_social if v.cliente else "")[:40]
        vend = ""
        if v.vendedor:
            vend = (v.vendedor.first_name or v.vendedor.username or "")[:20]
        print(
            "|".join(
                [
                    str(v.id),
                    str(v.ordem_servico or ""),
                    str(v.data_abertura.date() if v.data_abertura else ""),
                    str(v.data_criacao.date() if v.data_criacao else ""),
                    str(v.data_pedido.date() if getattr(v, "data_pedido", None) else ""),
                    (v.status_esteira.nome if v.status_esteira else "")[:20],
                    (v.status_tratamento.nome if v.status_tratamento else "")[:14],
                    vend,
                    cli.replace("|", "/"),
                ]
            ),
            flush=True,
        )


def main() -> None:
    ini, fim = date(2026, 8, 1), date(2026, 8, 31)
    jul_ini, jul_fim = date(2026, 7, 1), date(2026, 7, 31)

    qs_base = (
        Venda.objects.filter(ativo=True, reemissao=True)
        .exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico="")
        .select_related("cliente", "vendedor", "status_esteira", "status_tratamento")
    )

    a = qs_base.filter(
        status_tratamento__nome__iexact="CADASTRADA",
        data_abertura__date__gte=ini,
        data_abertura__date__lte=fim,
    ).order_by("data_abertura", "id")

    b = qs_base.filter(
        data_criacao__date__gte=ini,
        data_criacao__date__lte=fim,
    ).order_by("data_criacao", "id")

    c = qs_base.filter(
        data_abertura__date__gte=jul_ini,
        data_abertura__date__lte=jul_fim,
        data_criacao__date__gte=ini,
        data_criacao__date__lte=fim,
    ).order_by("id")

    # Diferença Esteira (com reemissão) vs Performance semanal (sem reemissão) no mês
    com = (
        Venda.objects.filter(
            ativo=True,
            status_tratamento__nome__iexact="CADASTRADA",
            data_abertura__date__gte=ini,
            data_abertura__date__lte=fim,
        )
        .exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico="")
    )
    print(f"TOTAL_OS_ABERTURA_AGO_COM_REEM={com.count()}", flush=True)
    print(
        f"TOTAL_OS_ABERTURA_AGO_SEM_REEM={com.filter(reemissao=False).count()}",
        flush=True,
    )
    print(f"REEM_ABERTURA_AGO={a.count()}", flush=True)
    print(f"REEM_CRIACAO_AGO={b.count()}", flush=True)
    print(f"REEM_ABERTURA_JUL_CRIACAO_AGO={c.count()}", flush=True)

    dump("A_reem_abertura_ago_cadastrada", a)
    dump("B_reem_criacao_ago", b)
    dump("C_reem_abertura_jul_criacao_ago", c)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERRO: {exc}", flush=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)
