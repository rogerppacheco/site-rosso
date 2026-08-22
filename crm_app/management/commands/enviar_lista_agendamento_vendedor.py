from django.core.management.base import BaseCommand

from crm_app.esteira_lista_agendamento_vendedor_service import (
    SLOT_MANHA,
    SLOT_TARDE,
    processar_disparo_lista_agendamento,
)


class Command(BaseCommand):
    help = (
        'Dispara a lista diária de agendamentos aos vendedores (imagem + botões). '
        'Uso: manage.py enviar_lista_agendamento_vendedor --periodo MANHA|TARDE'
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--periodo',
            choices=[SLOT_MANHA, SLOT_TARDE, 'manha', 'tarde'],
            required=True,
            help='Turno a enviar (MANHA ou TARDE).',
        )

    def handle(self, *args, **options) -> None:
        periodo = str(options['periodo']).upper()
        if periodo == 'MANHA':
            periodo = SLOT_MANHA
        elif periodo == 'TARDE':
            periodo = SLOT_TARDE
        resultado = processar_disparo_lista_agendamento(periodo)
        self.stdout.write(self.style.SUCCESS(str(resultado)))
