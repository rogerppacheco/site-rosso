"""
Corrige Venda.plano e valor_plano_pap a partir do payload do HistoricoPapPedido.

Usa resolver_plano_pap (nome + velocidade + valor mensal). Por padrão só simula.

Uso:
  python manage.py corrigir_plano_vendas_pap
  python manage.py corrigir_plano_vendas_pap --confirmar
  python manage.py corrigir_plano_vendas_pap --desde 2026-09-01 --ate 2026-09-12 --confirmar
  python manage.py corrigir_plano_vendas_pap --pedido 202609032661833367 --confirmar
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from crm_app.historico_pap import map_pedido_api
from crm_app.models import HistoricoPapPedido, Venda
from crm_app.services_sincronizacao import resolver_plano_pap


def _decimal_ou_none(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


class Command(BaseCommand):
    help = "Rematch Venda.plano e valor_plano_pap com dados do histórico PAP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Grava as alterações. Sem isto, só simula (dry-run).",
        )
        parser.add_argument(
            "--desde",
            type=str,
            default="",
            help="Filtra vendas com data_pedido/data_criacao >= YYYY-MM-DD",
        )
        parser.add_argument(
            "--ate",
            type=str,
            default="",
            help="Filtra vendas com data_pedido/data_criacao <= YYYY-MM-DD (inclusive)",
        )
        parser.add_argument(
            "--pedido",
            type=str,
            default="",
            help="Corrige um pedido PAP específico",
        )
        parser.add_argument(
            "--incluir-iguais",
            action="store_true",
            help="Lista também vendas já alinhadas",
        )

    def handle(self, *args, **options):
        confirmar = bool(options["confirmar"])
        incluir_iguais = bool(options["incluir_iguais"])
        pedido_filtro = (options.get("pedido") or "").strip()
        desde = self._parse_date(options.get("desde") or "", inicio=True)
        ate = self._parse_date(options.get("ate") or "", inicio=False)

        qs = Venda.objects.filter(pedido_pap__isnull=False).exclude(pedido_pap="")
        if pedido_filtro:
            qs = qs.filter(pedido_pap=pedido_filtro)
        if desde or ate:
            q_data = Q()
            if desde:
                q_data &= Q(data_pedido__gte=desde) | (
                    Q(data_pedido__isnull=True) & Q(data_criacao__gte=desde)
                )
            if ate:
                q_data &= Q(data_pedido__lte=ate) | (
                    Q(data_pedido__isnull=True) & Q(data_criacao__lte=ate)
                )
            qs = qs.filter(q_data)

        qs = qs.select_related("plano").order_by("id")
        total = qs.count()

        hist_por_pedido = {
            h.numero_pedido: h
            for h in HistoricoPapPedido.objects.filter(
                numero_pedido__in=list(qs.values_list("pedido_pap", flat=True)),
                tipo_venda=HistoricoPapPedido.TIPO_VENDA,
            )
        }

        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING("Corrigir plano/valor das vendas via histórico PAP"))
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(f"Vendas candidatas: {total}")
        self.stdout.write(f"Modo: {'GRAVAR' if confirmar else 'DRY-RUN'}")

        alteradas = 0
        iguais = 0
        sem_hist = 0
        sem_match = 0
        exemplos = []

        for venda in qs.iterator(chunk_size=200):
            hist = hist_por_pedido.get(venda.pedido_pap)
            if not hist or not hist.payload:
                sem_hist += 1
                continue

            mapped = map_pedido_api(hist.payload, hist.tipo_venda)
            valor_pap = _decimal_ou_none(mapped.get("valor_mensal"))
            plano_novo = resolver_plano_pap(
                mapped.get("plano") or "",
                mapped.get("velocidade") or "",
                mapped.get("valor_mensal"),
            )
            if not plano_novo:
                sem_match += 1
                exemplos.append(
                    f"  [sem match] pedido={venda.pedido_pap} "
                    f"pap={mapped.get('plano')!r} vel={mapped.get('velocidade')!r} "
                    f"atual={(venda.plano.nome if venda.plano_id else None)!r}"
                )
                continue

            valor_atual = _decimal_ou_none(venda.valor_plano_pap)
            plano_mudou = venda.plano_id != plano_novo.id
            valor_mudou = valor_pap is not None and valor_atual != valor_pap

            if not plano_mudou and not valor_mudou:
                iguais += 1
                if incluir_iguais:
                    exemplos.append(
                        f"  [ok] pedido={venda.pedido_pap} plano={plano_novo.nome} valor={valor_pap}"
                    )
                continue

            atual_nome = venda.plano.nome if venda.plano_id else None
            linha = (
                f"  venda={venda.id} pedido={venda.pedido_pap} "
                f"plano {atual_nome!r} -> {plano_novo.nome!r} | "
                f"valor {valor_atual} -> {valor_pap} "
                f"(PAP: {mapped.get('plano')} / {mapped.get('velocidade')})"
            )
            exemplos.append(linha)
            alteradas += 1

            if confirmar:
                updates = {"plano_id": plano_novo.id}
                if valor_pap is not None:
                    updates["valor_plano_pap"] = valor_pap
                with transaction.atomic():
                    Venda.objects.filter(id=venda.id).update(**updates)

        for linha in exemplos[:80]:
            self.stdout.write(linha)
        if len(exemplos) > 80:
            self.stdout.write(f"  ... +{len(exemplos) - 80} linhas")

        self.stdout.write("")
        self.stdout.write(f"A alterar / alteradas: {alteradas}")
        self.stdout.write(f"Já corretas: {iguais}")
        self.stdout.write(f"Sem histórico PAP: {sem_hist}")
        self.stdout.write(f"Sem match de plano: {sem_match}")
        if not confirmar and alteradas:
            self.stdout.write(self.style.NOTICE(
                "Dry-run concluído. Rode de novo com --confirmar para gravar."
            ))
        elif confirmar:
            self.stdout.write(self.style.SUCCESS(
                f"Gravadas {alteradas} correções de plano/valor."
            ))

    def _parse_date(self, value: str, *, inicio: bool):
        value = (value or "").strip()
        if not value:
            return None
        try:
            d = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"Data inválida: {value!r} (use YYYY-MM-DD)")
        if inicio:
            dt = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0))
        else:
            dt = timezone.make_aware(datetime(d.year, d.month, d.day, 23, 59, 59))
        return dt
