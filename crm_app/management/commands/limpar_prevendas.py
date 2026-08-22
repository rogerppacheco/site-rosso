"""
Comando: python manage.py limpar_prevendas
Remove todos os registros da tabela PreVenda (dados antigos).
Útil antes de rodar migrações que alteram a estrutura de PreVenda.
"""
from django.core.management.base import BaseCommand

from crm_app.models import PreVenda


class Command(BaseCommand):
    help = "Limpa dados antigos da tabela PreVenda."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Não pedir confirmação; executar direto.",
        )

    def handle(self, *args, **options):
        count = PreVenda.objects.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("Tabela PreVenda já está vazia."))
            return

        if not options["no_input"]:
            confirm = input(
                f"Remover {count} registro(s) de PreVenda? [y/N]: "
            ).strip().lower()
            if confirm != "y" and confirm != "yes":
                self.stdout.write("Operação cancelada.")
                return

        PreVenda.objects.all().delete()
        self.stdout.write(
            self.style.SUCCESS(f"✅ {count} registro(s) de PreVenda removidos.")
        )
        self.stdout.write(
            "Agora você pode executar: python manage.py migrate crm_app"
        )
