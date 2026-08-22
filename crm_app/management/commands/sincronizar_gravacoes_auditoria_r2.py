"""Arquiva gravações de auditoria no Cloudflare R2 até esgotar pendências."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from crm_app.services.auditoria_gravacao_sync_service import (
    queryset_ligacoes_pendentes_r2,
    sincronizar_todas_gravacoes_r2,
)


class Command(BaseCommand):
    help = (
        "Sincroniza gravações de auditoria para o Cloudflare R2 "
        "(Sonax, provedor e migração OneDrive). Repete em lotes até esgotar."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--lote",
            type=int,
            default=50,
            help="Quantidade de ligações por lote (padrão: 50).",
        )
        parser.add_argument(
            "--max-lotes",
            type=int,
            default=None,
            help="Limite de lotes por execução (padrão: sem limite, até esgotar).",
        )
        parser.add_argument(
            "--pausa",
            type=float,
            default=0.3,
            help="Pausa em segundos entre cada ligação (padrão: 0.3).",
        )

    def handle(self, *args, **options) -> None:
        lote = max(1, int(options["lote"]))
        max_lotes = options["max_lotes"]
        pausa = max(0.0, float(options["pausa"]))

        pendentes_inicio = queryset_ligacoes_pendentes_r2().count()
        self.stdout.write(f"Pendências no início: {pendentes_inicio}")

        if pendentes_inicio == 0:
            self.stdout.write(self.style.SUCCESS("Nenhuma gravação pendente para o R2."))
            return

        totais = sincronizar_todas_gravacoes_r2(
            lote=lote,
            max_lotes=max_lotes,
            pausa_segundos=pausa,
        )

        self.stdout.write(
            f"Lotes: {totais['lotes']} | "
            f"Processadas: {totais['processadas']} | "
            f"OK: {totais.get('ok', 0)} | "
            f"Skip: {totais.get('skip', 0)} | "
            f"Erro: {totais.get('erro', 0)} | "
            f"Erros únicos (indisponíveis): {totais.get('erros_unicos_sessao', 0)} | "
            f"Restantes: {totais['restantes']}"
        )

        if totais["restantes"] == 0:
            self.stdout.write(self.style.SUCCESS("Todas as gravações pendentes foram sincronizadas."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Ainda restam {totais['restantes']} ligações sem R2 "
                    "(gravação indisponível no provedor ou link expirado)."
                )
            )
