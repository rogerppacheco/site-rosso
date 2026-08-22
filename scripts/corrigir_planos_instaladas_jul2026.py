"""
Corrige planos de vendas INSTALADA (jul/2026) com base no cruzamento CRM x OSAB.

Regras (pedido do usuário):
1) Oferta com valor 75 -> NIO FIBRA ULTRA 1GB (SEM MESH)
2) Divergências óbvias de velocidade (ex.: CRM 600 / OSAB 500)
3) Oferta FIBRAX_MESH (sem 75) -> NIO FIBRA ULTRA 1GB

Uso:
  railway run --service site-record python scripts/corrigir_planos_instaladas_jul2026.py --dry-run
  railway run --service site-record python scripts/corrigir_planos_instaladas_jul2026.py --aplicar
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
# Prefere conexao direta (evita PgBouncer/proxy encerrar no meio do lote)
if os.environ.get("DATABASE_UNPOOLED_URL"):
    os.environ["DATABASE_URL"] = os.environ["DATABASE_UNPOOLED_URL"]
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction

from crm_app.models import HistoricoAlteracaoVenda, Plano, Venda

# plano_id produção (ativos)
PLANO_500 = 1  # NIO FIBRA ESSENCIAL 500MB
PLANO_600 = 6  # NIO FIBRA ESSENCIAL 600MB
PLANO_800 = 7  # NIO FIBRA SUPER 800MB
PLANO_1GB_MESH = 3  # NIO FIBRA ULTRA 1GB
PLANO_1GB_SEM_MESH = 5  # NIO FIBRA ULTRA 1GB (SEM MESH)

# ID venda -> plano_id alvo
# Fonte: Base_Vendas_Filtrada_20260802_1940 + regras do usuário
CORRECOES: dict[int, tuple[int, str]] = {
    # --- Oferta com 75 -> SEM MESH ---
    7689: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    7958: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8012: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8100: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8737: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8805: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8813: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8825: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8919: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    9144: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    9156: (PLANO_1GB_SEM_MESH, "Oferta com 75 -> SEM MESH"),
    8530: (PLANO_1GB_SEM_MESH, "CRM 500MB / OSAB 1GB oferta 75 -> SEM MESH"),
    # --- Velocidade óbvia ---
    8406: (PLANO_600, "CRM 500MB / OSAB 600MB"),
    8917: (PLANO_600, "CRM 500MB / OSAB 600MB"),
    8918: (PLANO_600, "CRM 500MB / OSAB 600MB"),
    8921: (PLANO_600, "CRM 500MB / OSAB 600MB"),
    9205: (PLANO_600, "CRM 500MB / OSAB 600MB"),
    7362: (PLANO_800, "CRM 500MB / OSAB 800MB"),
    8745: (PLANO_800, "CRM 500MB / OSAB 800MB"),
    8445: (PLANO_500, "CRM 600MB / OSAB 500MB"),
    9209: (PLANO_500, "CRM 600MB / OSAB 500MB"),
    8664: (PLANO_500, "CRM 1GB / OSAB 500MB"),
    8508: (PLANO_600, "CRM 1GB / OSAB 600MB"),
    8598: (PLANO_600, "CRM 1GB / OSAB 600MB"),
    # --- FIBRAX_MESH (sem regra 75) -> ULTRA 1GB ---
    9204: (PLANO_1GB_MESH, "CRM 600MB / OSAB 1GB FIBRAX_MESH"),
    9208: (PLANO_1GB_MESH, "CRM 600MB / OSAB 1GB FIBRAX_MESH"),
    7824: (PLANO_1GB_MESH, "CRM SEM MESH / Oferta FIBRAX_MESH"),
    8842: (PLANO_1GB_MESH, "CRM SEM MESH / Oferta FIBRAX_MESH"),
    8847: (PLANO_1GB_MESH, "CRM SEM MESH / Oferta FIBRAX_MESH"),
    9052: (PLANO_1GB_MESH, "CRM SEM MESH / Oferta FIBRAX_MESH"),
    9210: (PLANO_1GB_MESH, "CRM SEM MESH / Oferta FIBRAX_MESH"),
}


def _usuario_sistema():
    User = get_user_model()
    bot = User.objects.filter(username="OSAB_IMPORT").first()
    if bot:
        return bot
    return User.objects.filter(is_superuser=True).order_by("id").first()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Só lista, não grava")
    parser.add_argument("--aplicar", action="store_true", help="Aplica as correções")
    args = parser.parse_args()
    if not args.dry_run and not args.aplicar:
        print("Informe --dry-run ou --aplicar")
        return 1

    planos = {p.id: p for p in Plano.objects.filter(id__in={pid for pid, _ in CORRECOES.values()})}
    faltando = set(pid for pid, _ in CORRECOES.values()) - set(planos)
    if faltando:
        print(f"ERRO: planos não encontrados: {faltando}")
        return 1

    vendas = {
        v.id: v
        for v in Venda.objects.filter(id__in=CORRECOES.keys()).select_related("plano")
    }
    faltando_v = set(CORRECOES) - set(vendas)
    if faltando_v:
        print(f"AVISO: vendas não encontradas: {sorted(faltando_v)}")

    usuario = _usuario_sistema()
    print(f"Usuário histórico: {usuario.username if usuario else 'N/A'}")
    print(f"Total mapeado: {len(CORRECOES)}")

    a_aplicar: list[tuple[Venda, Plano, str]] = []
    ja_ok = 0
    for vid, (plano_id, motivo) in sorted(CORRECOES.items()):
        venda = vendas.get(vid)
        if not venda:
            continue
        alvo = planos[plano_id]
        atual = venda.plano
        if atual and atual.id == alvo.id:
            ja_ok += 1
            print(f"  SKIP #{vid} já está em {alvo.nome}")
            continue
        de = atual.nome if atual else "(sem plano)"
        print(f"  #{vid}  {de}  ->  {alvo.nome}  | {motivo}")
        a_aplicar.append((venda, alvo, motivo))

    print(f"\nJá corretas: {ja_ok}")
    print(f"A alterar: {len(a_aplicar)}")

    if args.dry_run or not a_aplicar:
        return 0

    # update() evita signals (M10/WhatsApp) que derrubam a conexao em lote via proxy.
    from django.utils import timezone
    from crm_app.models import ContratoM10

    ok = 0
    erros: list[str] = []
    for venda, alvo, motivo in a_aplicar:
        de_nome = venda.plano.nome if venda.plano else "Nenhum"
        try:
            with transaction.atomic():
                atualizados = Venda.objects.filter(pk=venda.pk).exclude(plano_id=alvo.id).update(
                    plano_id=alvo.id,
                    data_ultima_alteracao=timezone.now(),
                )
                if not atualizados:
                    print(f"  SKIP #{venda.pk} (ja atualizada)")
                    continue
                # Espelha plano no contrato Qualidade (sem recriar faturas)
                ContratoM10.objects.filter(venda_id=venda.pk).update(
                    plano_atual=alvo.nome,
                    valor_plano=alvo.valor,
                )
                HistoricoAlteracaoVenda.objects.create(
                    venda_id=venda.pk,
                    usuario=usuario,
                    alteracoes={
                        "plano": {"de": de_nome, "para": alvo.nome},
                        "_motivo": f"Correcao plano CRM x OSAB jul/2026: {motivo}",
                    },
                )
            ok += 1
            print(f"  OK #{venda.pk}")
        except Exception as exc:
            msg = f"#{venda.pk}: {exc}"
            erros.append(msg)
            print(f"  ERRO {msg}")
            from django.db import connection

            connection.close()

    print(f"OK: {ok} vendas atualizadas. Erros: {len(erros)}")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
