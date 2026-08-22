"""
Testa a automação de 2ª via Nio (site sem reCAPTCHA).

Uso:
  python manage.py testar_segunda_via_nio --cpf 12345678901

  python manage.py testar_segunda_via_nio --cpf 12345678901 --visible
    -> Abre o navegador visível
"""
import re

from django.core.management.base import BaseCommand

from crm_app.services_nio import buscar_fatura_segunda_via_site


class Command(BaseCommand):
    help = "Testa buscar fatura no site 2ª via Nio (www.niointernet.com.br)"

    def add_arguments(self, parser):
        parser.add_argument("--cpf", required=True, help="CPF (apenas números)")
        parser.add_argument(
            "--visible",
            action="store_true",
            help="Abre o navegador visível (headless=False)",
        )
        parser.add_argument(
            "--sem-pdf",
            action="store_true",
            help="Não tentar baixar PDF",
        )

    def handle(self, *args, **options):
        cpf = re.sub(r"\D", "", options["cpf"] or "")
        if not cpf or len(cpf) != 11:
            self.stderr.write(self.style.ERROR("CPF inválido. Use 11 dígitos."))
            return

        self.stdout.write(f"Buscando fatura para CPF: {cpf}")
        self.stdout.write("Aguarde...")

        invoices = buscar_fatura_segunda_via_site(
            cpf,
            incluir_pdf=not options.get("sem_pdf", False),
            headless=not options.get("visible", False),
        )

        if not invoices:
            self.stdout.write(self.style.WARNING("Nenhuma fatura encontrada."))
            return

        for i, inv in enumerate(invoices, 1):
            self.stdout.write(self.style.SUCCESS(f"\n--- Fatura {i} ---"))
            self.stdout.write(f"Valor: R$ {inv.get('amount', 'N/A')}")
            self.stdout.write(f"Vencimento: {inv.get('due_date_raw') or inv.get('data_vencimento')}")
            self.stdout.write(f"Status: {inv.get('status', 'N/A')}")
            pix = inv.get("pix") or inv.get("codigo_pix")
            if pix:
                self.stdout.write(f"PIX: {pix[:60]}...")
            if inv.get("pdf_path"):
                self.stdout.write(self.style.SUCCESS(f"PDF: {inv['pdf_path']}"))
