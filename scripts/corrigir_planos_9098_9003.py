"""Aplica plano ULTRA 1GB (SEM MESH) nas vendas 9098 e 9003."""
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

from crm_app.models import ContratoM10, HistoricoAlteracaoVenda, Plano, Venda

IDS = [9098, 9003]
ALVO_NOME = "NIO FIBRA ULTRA 1GB (SEM MESH)"


def main() -> int:
    alvo = Plano.objects.get(nome=ALVO_NOME, ativo=True)
    usuario = get_user_model().objects.filter(username="OSAB_IMPORT").first()
    print(f"Alvo: id={alvo.id} {alvo.nome} R${alvo.valor}")

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
                    "_motivo": "Correcao plano CRM x OSAB: 500MB -> 1GB SEM MESH (oferta 75)",
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
