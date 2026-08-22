#!/usr/bin/env python
"""
Comando de management para corrigir vendas com reemissão=True para terem status_esteira=AGENDADO
"""
from django.core.management.base import BaseCommand
from crm_app.models import Venda, StatusCRM


class Command(BaseCommand):
    help = 'Corrige vendas com reemissão=True para terem status_esteira=AGENDADO e aparecerem na esteira'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula a execução sem fazer alterações no banco de dados',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Buscar status AGENDADO
        try:
            status_agendado = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
        except StatusCRM.DoesNotExist:
            self.stdout.write(self.style.ERROR('Status "AGENDADO" (Esteira) não encontrado no banco de dados.'))
            return
        
        # Buscar vendas com reemissão=True
        vendas_reemissao = Venda.objects.filter(reemissao=True, ativo=True)
        
        self.stdout.write(f'Encontradas {vendas_reemissao.count()} vendas com reemissão=True')
        
        atualizadas = 0
        ja_agendadas = 0
        
        for venda in vendas_reemissao:
            if venda.status_esteira and venda.status_esteira.nome.upper() == 'AGENDADO':
                ja_agendadas += 1
                continue
            
            if not dry_run:
                venda.status_esteira = status_agendado
                venda.save(update_fields=['status_esteira'])
            
            atualizadas += 1
            self.stdout.write(f'  Venda #{venda.id} (OS: {venda.ordem_servico or "N/A"}) - Status atualizado para AGENDADO')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'\n[MODO DRY-RUN] Nenhuma alteração foi feita.'))
            self.stdout.write(f'  Vendas que seriam atualizadas: {atualizadas}')
            self.stdout.write(f'  Vendas já com status AGENDADO: {ja_agendadas}')
        else:
            self.stdout.write(self.style.SUCCESS(f'\n✅ Processo concluído!'))
            self.stdout.write(f'  Vendas atualizadas: {atualizadas}')
            self.stdout.write(f'  Vendas já com status AGENDADO: {ja_agendadas}')
