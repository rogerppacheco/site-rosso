"""Corrige IDs 8788, 9210, 8436, 8376 para ULTRA 1GB (SEM MESH)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
if os.environ.get("DATABASE_UNPOOLED_URL"):
    os.environ["DATABASE_URL"] = os.environ["DATABASE_UNPOOLED_URL"]
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from crm_app.models import ContratoM10, HistoricoAlteracaoVenda, ImportacaoOsab, Plano, Venda

IDS = [8788, 9210, 8436, 8376]
ALVO_NOME = "NIO FIBRA ULTRA 1GB (SEM MESH)"


def main() -> int:
    alvo = Plano.objects.get(nome=ALVO_NOME, ativo=True)
    usuario = get_user_model().objects.filter(username="OSAB_IMPORT").first()
    print(f"Alvo: id={alvo.id} {alvo.nome}")

    for vid in IDS:
        v = Venda.objects.select_related("plano", "cliente").get(pk=vid)
        os_val = (v.ordem_servico or "").strip()
        osab = ImportacaoOsab.objects.filter(documento=os_val).first()
        print(
            f"#{vid} CRM={v.plano.nome if v.plano else '-'} "
            f"OSAB_vel={osab.velocidade if osab else '-'} "
            f"OSAB_oferta={osab.oferta if osab else '-'} "
            f"OS={os_val}"
        )

    ok = 0
    for vid in IDS:
        venda = Venda.objects.select_related("plano").get(pk=vid)
        de_nome = venda.plano.nome if venda.plano else "Nenhum"
        if venda.plano_id == alvo.id:
            print(f"SKIP #{vid} ja esta em {alvo.nome}")
            continue
        with transaction.atomic():
            Venda.objects.filter(pk=vid).update(
                plano_id=alvo.id,
                data_ultima_alteracao=timezone.now(),
            )
            ContratoM10.objects.filter(venda_id=vid).update(
                plano_atual=alvo.nome,
                valor_plano=alvo.valor,
            )
            HistoricoAlteracaoVenda.objects.create(
                venda_id=vid,
                usuario=usuario,
                alteracoes={
                    "plano": {"de": de_nome, "para": alvo.nome},
                    "_motivo": (
                        "Correcao plano: ULTRA 1GB -> ULTRA 1GB (SEM MESH) "
                        "(ofertas 150/135 ou FIBRAX_MESH_155_140)"
                    ),
                },
            )
        print(f"OK #{vid} {de_nome} -> {alvo.nome}")
        ok += 1

    print(f"Atualizadas: {ok}")
    for v in Venda.objects.filter(id__in=IDS).select_related("plano"):
        print(f"CHECK #{v.id} = {v.plano.nome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
