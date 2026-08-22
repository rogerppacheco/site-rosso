"""Match noturno CRM ↔ Nio (janela 22h–7h).

Uso:
  python manage.py match_faturas_nio_noturno
  python manage.py match_faturas_nio_noturno --limite 20 --forcar
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from crm_app.services.nio_match_service import processar_lote_match_noturno


class Command(BaseCommand):
    help = "Casa faturas abertas com a Nio (PIX/barras/valor) só quando o match é único."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limite",
            type=int,
            default=0,
            help="Contratos neste lote (0 = settings MATCH_NIO_LOTE, padrão 120)",
        )
        parser.add_argument(
            "--forcar",
            action="store_true",
            help="Ignora a janela 22h–7h (útil para teste)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        limite = int(options.get("limite") or 0)
        if limite <= 0:
            limite = int(getattr(settings, "MATCH_NIO_LOTE", 30) or 30)
        data = processar_lote_match_noturno(
            limite=limite,
            forcar=bool(options.get("forcar")),
        )
        if data.get("pulado"):
            self.stdout.write(self.style.WARNING(f"Pulado: {data.get('motivo')}"))
            return
        resumo = data.get("resumo") or {}
        self.stdout.write(
            self.style.SUCCESS(
                f"historico={data.get('historico_id')} processados={data.get('processados')} "
                f"restam={data.get('restam')} match={resumo.get('match', 0)} "
                f"ambiguo={resumo.get('ambiguo', 0)} sem_match={resumo.get('sem_match', 0)}"
            )
        )
