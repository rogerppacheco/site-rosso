"""
Sincroniza Venda.data_abertura (CRM) com ImportacaoOsab.data_abertura (espelho OSAB).

Uso:
  python manage.py sincronizar_data_abertura_osab_crm
  python manage.py sincronizar_data_abertura_osab_crm --aplicar
  python manage.py sincronizar_data_abertura_osab_crm --ids 6506,6497 --aplicar
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import datetime

from crm_app.churn_os_utils import os_variantes
from crm_app.models import HistoricoAlteracaoVenda, ImportacaoOsab, Venda
from crm_app.osab_datetime_utils import (
    format_osab_datetime_local,
    osab_datetimes_differ,
    osab_datetime_to_aware,
)


class Command(BaseCommand):
    help = "Alinha Data Abertura (OS) do CRM com DATA_ABERTURA da base espelho OSAB."

    def add_arguments(self, parser):
        parser.add_argument("--ids", type=str, default="", help="IDs de venda separados por vírgula.")
        parser.add_argument("--aplicar", action="store_true", help="Grava alterações (padrão: dry-run).")
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Sincroniza mesmo quando espelho OSAB só tem 00:00:00 (após reimportação completa).",
        )

    def handle(self, *args, **options):
        ids_filtro = None
        if options.get("ids"):
            ids_filtro = {int(x.strip()) for x in options["ids"].split(",") if x.strip()}

        osab_by_key = {}
        for o in ImportacaoOsab.objects.exclude(documento__isnull=True).exclude(documento="").iterator(
            chunk_size=5000
        ):
            if not o.data_abertura:
                continue
            for k in os_variantes(o.documento):
                osab_by_key.setdefault(k, o)

        qs = Venda.objects.filter(ativo=True).exclude(
            Q(ordem_servico__isnull=True) | Q(ordem_servico="")
        ).select_related("forma_pagamento")
        if ids_filtro:
            qs = qs.filter(id__in=ids_filtro)

        alterar = []
        sem_osab = 0
        sem_data_osab = 0
        ja_iguais = 0
        adiados_so_data_osab = 0

        for v in qs.iterator(chunk_size=500):
            o = None
            for k in os_variantes(v.ordem_servico):
                o = osab_by_key.get(k)
                if o:
                    break
            if not o:
                sem_osab += 1
                continue
            if not o.data_abertura:
                sem_data_osab += 1
                continue

            novo = osab_datetime_to_aware(o.data_abertura)
            if not novo:
                sem_data_osab += 1
                continue
            if timezone.localtime(novo).year < 2000:
                continue

            if not osab_datetimes_differ(v.data_abertura, novo):
                ja_iguais += 1
                continue

            novo_local = timezone.localtime(novo)
            crm_local = timezone.localtime(v.data_abertura) if v.data_abertura else None
            osab_meia_noite_local = (
                novo_local.hour == 0
                and novo_local.minute == 0
                and novo_local.second == 0
            )
            crm_tem_hora_real = (
                crm_local
                and (crm_local.hour, crm_local.minute, crm_local.second) != (0, 0, 0)
            )
            mesmo_dia_local = (
                crm_local is not None and crm_local.date() == novo_local.date()
            )
            # Espelho ainda só com data (00:00 local): não sobrescrever hora do CRM
            if (
                not options["forcar"]
                and osab_meia_noite_local
                and crm_tem_hora_real
                and mesmo_dia_local
            ):
                adiados_so_data_osab += 1
                continue
            # Só data no espelho e dia diferente: alinhar dia mantendo hora do CRM se existir
            if (
                not options["forcar"]
                and osab_meia_noite_local
                and crm_local
                and not mesmo_dia_local
            ):
                novo = timezone.make_aware(
                    datetime.combine(
                        novo_local.date(),
                        crm_local.time(),
                    ),
                    timezone.get_current_timezone(),
                )
            elif (
                not options["forcar"]
                and osab_meia_noite_local
                and not crm_local
            ):
                pass  # usa meia-noite OSAB

            crm_antes = format_osab_datetime_local(v.data_abertura)
            crm_depois = format_osab_datetime_local(novo)
            alterar.append((v, novo, crm_antes, crm_depois, o.documento))

        limite = options.get("limite") or 0
        aplicar_lista = alterar[:limite] if limite else alterar

        self.stdout.write(
            f"Divergentes: {len(alterar)} | Já iguais: {ja_iguais} | "
            f"Adiados (OSAB só data, CRM com hora): {adiados_so_data_osab} | "
            f"Sem espelho OSAB: {sem_osab} | OSAB sem data: {sem_data_osab} | "
            f"dry_run={not options['aplicar']}"
        )
        for v, _novo, antes, depois, doc in aplicar_lista[:30]:
            self.stdout.write(
                f"  id={v.id} os={v.ordem_servico} doc_osab={doc} | CRM={antes} -> OSAB={depois}"
            )
        if len(aplicar_lista) > 30:
            self.stdout.write(f"  ... +{len(aplicar_lista) - 30} linhas")

        if not options["aplicar"] or not alterar:
            if not options["aplicar"] and alterar:
                self.stdout.write(self.style.WARNING("Use --aplicar para gravar."))
            return

        vendas_bulk = []
        historicos = []
        for v, novo, antes, depois, _doc in aplicar_lista:
            v.data_abertura = novo
            vendas_bulk.append(v)
            historicos.append(
                HistoricoAlteracaoVenda(
                    venda=v,
                    usuario=None,
                    alteracoes={
                        "data_abertura": (
                            f"De '{antes}' para '{depois}' "
                            "(sincronização DATA_ABERTURA OSAB → CRM)"
                        ),
                    },
                )
            )

        with transaction.atomic():
            Venda.objects.bulk_update(vendas_bulk, ["data_abertura"], batch_size=500)
            HistoricoAlteracaoVenda.objects.bulk_create(historicos, batch_size=500)

        self.stdout.write(self.style.SUCCESS(f"Atualizadas {len(vendas_bulk)} vendas."))
