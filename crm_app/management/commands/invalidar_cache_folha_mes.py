"""Invalida o cache da folha de comissionamento de um mês (após deploy ou correção de regras)."""
from django.core.management.base import BaseCommand

from crm_app.services.folha_comissionamento_cache import invalidar_folha_mes, obter_versao_cache


class Command(BaseCommand):
    help = 'Invalida cache da folha de comissionamento para ano/mês (ex.: --ano 2026 --mes 5).'

    def add_arguments(self, parser) -> None:
        parser.add_argument('--ano', type=int, required=True)
        parser.add_argument('--mes', type=int, required=True)

    def handle(self, *args, **options) -> None:
        ano, mes = options['ano'], options['mes']
        if not (1 <= mes <= 12):
            self.stdout.write(self.style.ERROR('Mês inválido.'))
            return

        versao_antes = obter_versao_cache(ano, mes)
        invalidar_folha_mes(ano, mes)
        versao_depois = obter_versao_cache(ano, mes)
        self.stdout.write(
            self.style.SUCCESS(
                f'Cache da folha {mes:02d}/{ano} invalidado: versao {versao_antes} -> {versao_depois}'
            )
        )
