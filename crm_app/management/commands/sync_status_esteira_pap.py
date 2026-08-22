"""Sincroniza status da esteira (AGENDADO/PENDENCIADA) via PAP — job noturno ou manual."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Sincroniza pedidos AGENDADO/PENDENCIADA da esteira consultando o PAP (fluxo STATUS)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--modo',
            choices=['automatico', 'manual'],
            default='automatico',
            help='automatico: só inicia se estiver na janela 22h–07h e sem job em andamento',
        )

    def handle(self, *args, **options):
        from crm_app.esteira_sync_status_pap_service import (
            criar_e_iniciar_execucao_manual,
            tentar_iniciar_automatico,
        )

        modo = options['modo']
        if modo == 'automatico':
            if tentar_iniciar_automatico():
                self.stdout.write(self.style.SUCCESS('Sync esteira automático concluído/iniciado.'))
            else:
                self.stdout.write('Sync esteira automático não iniciado (janela, conflito ou em andamento).')
            return

        exec_id, err = criar_e_iniciar_execucao_manual()
        if err:
            self.stdout.write(self.style.ERROR(err))
            return
        self.stdout.write(self.style.SUCCESS(f'Sync esteira manual iniciado (execução #{exec_id}).'))
