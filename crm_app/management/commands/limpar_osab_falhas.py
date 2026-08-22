from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.models import LogImportacaoOSAB


class Command(BaseCommand):
    help = "Remove logs de importação OSAB que falharam."

    def add_arguments(self, parser):
        parser.add_argument(
            "--status",
            nargs="+",
            default=["ERRO"],
            help="Status a limpar (ex: ERRO PARCIAL). Padrão: ERRO",
        )
        parser.add_argument(
            "--older-than",
            type=int,
            default=None,
            help="Somente logs mais antigos que N dias.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas mostra o que seria removido, sem apagar.",
        )

    def handle(self, *args, **options):
        statuses = [s.upper() for s in options["status"]]
        older_than = options["older_than"]
        dry_run = options["dry_run"]

        qs = LogImportacaoOSAB.objects.filter(status__in=statuses)

        if older_than is not None:
            cutoff = timezone.now() - timedelta(days=older_than)
            qs = qs.filter(iniciado_em__lt=cutoff)

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("Nenhum log OSAB encontrado para limpar."))
            return

        self.stdout.write(
            f"Logs OSAB encontrados para limpeza: {total} "
            f"(status={statuses}, older_than={older_than} dias)"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run ativo. Nenhum registro foi removido."))
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Logs OSAB removidos: {deleted}"))
