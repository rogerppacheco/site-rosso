# -*- coding: utf-8 -*-
"""
Preenche o cache persistente CEP -> cidade com todos os CEPs distintos da base CNPJ.
Rode uma vez (ou periodicamente) para garantir que todos os CEPs tenham cidade atribuída.
O cache fica em crm_app/data/cep_localidade_cache.json e é usado automaticamente nas exportações.

Exemplo:
  python manage.py preencher_cache_cep
  python manage.py preencher_cache_cep --uf MG
  python manage.py preencher_cache_cep --delay 0.2
"""
import time
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Preenche cache CEP -> cidade com os CEPs da base CNPJ (ViaCEP + OpenCEP).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--uf',
            type=str,
            default=None,
            help='Filtrar apenas CEPs de uma UF (ex: MG). Se não informado, processa todos.',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.15,
            help='Segundos entre consultas à API (default 0.15) para não sobrecarregar.',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=0,
            help='Máximo de CEPs a processar (0 = todos).',
        )

    def handle(self, *args, **options):
        from crm_app.models import ImportacaoEstabelecimentoCNPJ
        from crm_app.services.cep_lookup import get_municipio_por_cep, get_cache_stats, _load_file_cache

        uf = (options.get('uf') or '').strip().upper()[:2] or None
        delay = max(0.05, min(2.0, options.get('delay') or 0.15))
        limite = max(0, options.get('limite') or 0)

        qs = ImportacaoEstabelecimentoCNPJ.objects.filter(situacao_cadastral='02').exclude(cep__isnull=True).exclude(cep='')
        if uf:
            qs = qs.filter(uf=uf)
        ceps_raw = list(qs.values_list('cep', flat=True).distinct())
        ceps_norm = set()
        for c in ceps_raw:
            s = ''.join(x for x in (c or '') if x.isdigit())[:8]
            if len(s) == 8:
                ceps_norm.add(s)

        ceps_ordenados = sorted(ceps_norm)
        if limite:
            ceps_ordenados = ceps_ordenados[:limite]

        _load_file_cache()
        antes = get_cache_stats()
        self.stdout.write('CEPs distintos a processar: %d (UF=%s)' % (len(ceps_ordenados), uf or 'todos'))
        self.stdout.write('Cache antes: %d CEPs' % antes)

        cache_mem = {}
        processados = 0
        erros = 0
        for i, cep in enumerate(ceps_ordenados):
            if (i + 1) % 500 == 0:
                self.stdout.write('  %d / %d' % (i + 1, len(ceps_ordenados)))
            processados += 1
            nome = get_municipio_por_cep(cep, cache=cache_mem, persist=True)
            if not nome:
                erros += 1
            time.sleep(delay)

        depois = get_cache_stats()
        novos = depois - antes
        self.stdout.write(self.style.SUCCESS(
            'Concluído. Processados: %d | Novos no cache: %d | Sem cidade: %d | Cache total: %d' % (
                processados, novos, erros, depois
            )
        ))
