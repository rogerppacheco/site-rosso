# -*- coding: utf-8 -*-
"""
Limpa a tabela de estabelecimentos CNPJ (Receita Federal) e opcionalmente
marca logs "Processando" como "Parcial" ou apaga todos os logs.

Use antes de reimportar um arquivo gigante após uma importação que parou no meio.

Uso:
    python manage.py limpar_cnpj_estabelecimentos --confirmar
    python manage.py limpar_cnpj_estabelecimentos --confirmar --marcar-parcial
    python manage.py limpar_cnpj_estabelecimentos --confirmar --incluir-logs
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Limpa a tabela de estabelecimentos CNPJ (para reimportar do zero)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirmar',
            action='store_true',
            help='Confirma a limpeza (sem isso, apenas mostra o que seria feito)',
        )
        parser.add_argument(
            '--marcar-parcial',
            action='store_true',
            help='Marca logs com status PROCESSANDO como PARCIAL (importação interrompida)',
        )
        parser.add_argument(
            '--incluir-logs',
            action='store_true',
            help='Apaga também todos os logs de importação CNPJ (histórico zerado)',
        )

    def handle(self, *args, **options):
        from crm_app.models import ImportacaoEstabelecimentoCNPJ, LogImportacaoEstabelecimentoCNPJ
        from django.utils import timezone

        confirmar = options['confirmar']
        marcar_parcial = options['marcar_parcial']
        incluir_logs = options['incluir_logs']

        total = ImportacaoEstabelecimentoCNPJ.objects.count()
        total_logs = LogImportacaoEstabelecimentoCNPJ.objects.count()
        logs_processando = LogImportacaoEstabelecimentoCNPJ.objects.filter(status='PROCESSANDO').count()

        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write(self.style.WARNING('Limpeza da base CNPJ (Estabelecimentos Receita Federal)'))
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write('')
        self.stdout.write(f'Registros na tabela cnpj: {total:,}')
        self.stdout.write(f'Logs de importação CNPJ: {total_logs:,}')
        if marcar_parcial and not incluir_logs:
            self.stdout.write(f'  → Logs em PROCESSANDO (serão marcados PARCIAL): {logs_processando}')
        if incluir_logs:
            self.stdout.write('  → Todos os logs serão APAGADOS (--incluir-logs)')
        self.stdout.write('')

        if not confirmar:
            self.stdout.write(self.style.WARNING('MODO SIMULAÇÃO – nenhum dado foi alterado.'))
            self.stdout.write('')
            self.stdout.write('Para limpar de verdade, execute:')
            self.stdout.write(self.style.SUCCESS('  python manage.py limpar_cnpj_estabelecimentos --confirmar'))
            if logs_processando and not incluir_logs:
                self.stdout.write(self.style.SUCCESS('  python manage.py limpar_cnpj_estabelecimentos --confirmar --marcar-parcial'))
            if total_logs:
                self.stdout.write(self.style.SUCCESS('  python manage.py limpar_cnpj_estabelecimentos --confirmar --incluir-logs'))
            return

        try:
            # TRUNCATE é muito mais rápido que DELETE para milhões de linhas
            self.stdout.write('Truncando tabela crm_importacao_estabelecimento_cnpj...')
            with connection.cursor() as cursor:
                cursor.execute(
                    'TRUNCATE TABLE crm_importacao_estabelecimento_cnpj RESTART IDENTITY'
                )
            self.stdout.write(self.style.SUCCESS(f'Tabela limpa. ({total:,} registros removidos.)'))

            if marcar_parcial and logs_processando and not incluir_logs:
                LogImportacaoEstabelecimentoCNPJ.objects.filter(status='PROCESSANDO').update(
                    status='PARCIAL',
                    finalizado_em=timezone.now(),
                    mensagem='Importação interrompida (parou antes de concluir).',
                )
                self.stdout.write(self.style.SUCCESS(f'{logs_processando} log(s) marcado(s) como PARCIAL.'))

            if incluir_logs and total_logs:
                LogImportacaoEstabelecimentoCNPJ.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f'{total_logs:,} log(s) de importação apagado(s).'))

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('Limpeza concluída. Pode reimportar o arquivo ESTABELE.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erro: {e}'))
            raise
