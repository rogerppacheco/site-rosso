#!/usr/bin/env python
"""
Comando para corrigir a Data Abertura (OS) de uma venda por ID.
Uso em produção: python manage.py corrigir_data_abertura 3192 --data "21/02/2026" --hora "20:20"
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from crm_app.models import Venda


class Command(BaseCommand):
    help = 'Corrige a Data Abertura (OS) de uma venda por ID. Ex: corrigir_data_abertura 3192 --data "21/02/2026" --hora "20:20"'

    def add_arguments(self, parser):
        parser.add_argument('venda_id', type=int, help='ID da venda (ex: 3192)')
        parser.add_argument('--data', type=str, required=True, help='Nova data no formato DD/MM/AAAA (ex: 21/02/2026)')
        parser.add_argument('--hora', type=str, default='00:00', help='Hora no formato HH:MM (ex: 20:20). Default: 00:00')
        parser.add_argument('--dry-run', action='store_true', help='Apenas mostra o que seria alterado, sem gravar')

    def handle(self, *args, **options):
        venda_id = options['venda_id']
        data_str = options['data'].strip()
        hora_str = options['hora'].strip()
        dry_run = options['dry_run']

        try:
            dia, mes, ano = data_str.split('/')
            hora, minuto = hora_str.split(':')
            dt_naive = datetime(
                int(ano), int(mes), int(dia),
                int(hora), int(minuto), 0, 0
            )
        except (ValueError, AttributeError) as e:
            self.stdout.write(self.style.ERROR(
                f'Data ou hora inválida. Use --data "DD/MM/AAAA" e --hora "HH:MM". Erro: {e}'
            ))
            return

        # Interpretar como horário local (America/Sao_Paulo) e converter para o que o Django espera
        nova_abertura = timezone.make_aware(dt_naive, timezone.get_current_timezone())

        try:
            venda = Venda.objects.get(pk=venda_id)
        except Venda.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Venda com ID {venda_id} não encontrada.'))
            return

        antiga = venda.data_abertura
        antiga_str = timezone.localtime(antiga).strftime('%d/%m/%Y %H:%M') if antiga else '-'
        nova_str = timezone.localtime(nova_abertura).strftime('%d/%m/%Y %H:%M')

        self.stdout.write(f'Venda ID: {venda.id}')
        self.stdout.write(f'  Data Abertura (OS) atual:  {antiga_str}')
        self.stdout.write(f'  Data Abertura (OS) nova:   {nova_str}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY-RUN] Nenhuma alteração feita. Rode sem --dry-run para aplicar.'))
            return

        venda.data_abertura = nova_abertura
        venda.save(update_fields=['data_abertura'])
        self.stdout.write(self.style.SUCCESS(f'\nData Abertura da venda {venda_id} atualizada para {nova_str}.'))
