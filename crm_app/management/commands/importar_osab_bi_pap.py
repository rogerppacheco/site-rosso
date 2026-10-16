"""
Exporta OSAB do BI (Dinâmica - OSAB) no portal PAP e importa na Central.

Uso:
  python manage.py importar_osab_bi_pap
  python manage.py importar_osab_bi_pap --matricula TT713110
  python manage.py importar_osab_bi_pap --headed --pular-importacao
"""
from django.core.management.base import BaseCommand, CommandError

from crm_app.services.import_osab_bi_pap_service import exportar_e_importar_osab_bi


class Command(BaseCommand):
    help = (
        "Baixa a base Exportação-OSAB do Power BI (PAP) e importa no CRM. "
        "Usa Conta de Serviço PAP com função Importação OSAB (BI Dinâmica)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--matricula",
            default="",
            help="Matrícula da conta robô (senão usa a primeira IMPORT_OSAB_BI ativa).",
        )
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Abre o navegador visível (debug).",
        )
        parser.add_argument(
            "--enviar-whatsapp",
            action="store_true",
            help="Permite WhatsApp na importação OSAB (padrão: silencioso).",
        )
        parser.add_argument(
            "--pular-importacao",
            action="store_true",
            help="Só exporta o arquivo, sem chamar o import OSAB.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Iniciando exportação BI Dinâmica OSAB → import CRM…")
        res = exportar_e_importar_osab_bi(
            matricula=options.get("matricula") or "",
            headless=not options.get("headed"),
            enviar_whatsapp=bool(options.get("enviar_whatsapp")),
            pular_importacao=bool(options.get("pular_importacao")),
        )
        msg = (
            f"matricula={res.matricula} arquivo={res.arquivo} "
            f"bytes={res.bytes_arquivo} log_id={res.log_id} "
            f"status={res.log_status} detail={res.detail}"
        )
        if res.ok:
            self.stdout.write(self.style.SUCCESS(msg))
        else:
            self.stderr.write(self.style.ERROR(msg))
            raise CommandError(msg)
