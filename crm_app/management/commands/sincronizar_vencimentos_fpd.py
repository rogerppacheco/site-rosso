"""Corrige vencimentos das faturas M-10 com a data da planilha FPD/SPD/TPD."""
from django.core.management.base import BaseCommand

from crm_app.services.fpd_import_service import sincronizar_vencimentos_fpd_nas_faturas


class Command(BaseCommand):
    help = (
        'Sincroniza FaturaM10.data_vencimento a partir de ImportacaoFPD '
        '(planilha é a fonte da verdade).'
    )

    def handle(self, *args, **options):
        resultado = sincronizar_vencimentos_fpd_nas_faturas()
        self.stdout.write(self.style.SUCCESS(str(resultado)))
