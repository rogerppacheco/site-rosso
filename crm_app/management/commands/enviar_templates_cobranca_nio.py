"""
Dispara templates Meta de cobrança Nio (D−5, D+5, recorrente a cada 7 dias).

Uso:
  python manage.py enviar_templates_cobranca_nio
  python manage.py enviar_templates_cobranca_nio --dry-run
  python manage.py enviar_templates_cobranca_nio --limite 20
"""
from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from crm_app.services.qualidade_service import (
    enviar_cobranca_whatsapp,
    ja_enviou_template_cobranca_hoje,
    listar_alvos_cobranca_templates,
    pode_tratar_contrato,
    validar_fatura_para_envio_cobranca,
)


class Command(BaseCommand):
    help = "Envia templates Meta de cobrança (lembrete D−5, vencida D+5, recorrente)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Só lista, não envia")
        parser.add_argument(
            "--limite",
            type=int,
            default=0,
            help="Máximo de envios nesta execução (0 = todos os elegíveis)",
        )
        parser.add_argument(
            "--apenas",
            choices=["d5_antes", "d5_depois", "recorrente", "todos"],
            default="todos",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry = bool(options["dry_run"])
        limite = max(0, int(options["limite"] or 0))
        pausa_ms = max(0, int(getattr(settings, "COBRANCA_NIO_PAUSA_MS", 300) or 0))
        apenas = options["apenas"]
        enviados = 0
        erros = 0
        pulados = 0

        alvos = listar_alvos_cobranca_templates(apenas=apenas)
        vistos: set[int] = set()

        for tipo, fatura in alvos:
            if limite > 0 and enviados >= limite:
                break
            if fatura.id in vistos:
                continue
            vistos.add(fatura.id)

            if ja_enviou_template_cobranca_hoje(fatura):
                pulados += 1
                continue

            contrato = fatura.contrato
            if not pode_tratar_contrato(contrato):
                pulados += 1
                continue

            ok_dados, motivo = validar_fatura_para_envio_cobranca(fatura)
            if not ok_dados:
                pulados += 1
                self.stdout.write(f"  skip dados fatura={fatura.id}: {motivo}")
                continue

            self.stdout.write(
                f"[{tipo}] fatura={fatura.id} contrato={contrato.id} "
                f"venc={fatura.data_vencimento} valor={fatura.valor}"
            )
            if dry:
                enviados += 1
                continue

            result = enviar_cobranca_whatsapp(
                contrato.id,
                fatura.id,
                user=None,
                modo="template",
            )
            if result.get("ok"):
                enviados += 1
                self.stdout.write(self.style.SUCCESS(f"  ok canal={result.get('canal')}"))
            else:
                erros += 1
                self.stdout.write(self.style.ERROR(f"  falha: {result.get('erro')}"))
            if pausa_ms > 0:
                time.sleep(pausa_ms / 1000.0)

        self.stdout.write(
            self.style.NOTICE(
                f"Concluído: enviados={enviados} erros={erros} pulados={pulados} dry_run={dry}"
            )
        )
