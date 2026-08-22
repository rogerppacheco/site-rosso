# -*- coding: utf-8 -*-
"""
Lista os códigos de município (Cod.Municipio) da base CNPJ que o sistema não consegue
cruzar com o IBGE (get_nome_municipio_por_codigo retorna vazio).
Útil para entender quais códigos vêm da Receita mas não existem na base IBGE atual.

Uso:
  python manage.py listar_codigos_municipio_sem_ibge
  python manage.py listar_codigos_municipio_sem_ibge --uf MG --saida codigos_sem_ibge.txt
"""
from django.core.management.base import BaseCommand

from crm_app.models import ImportacaoEstabelecimentoCNPJ
from crm_app.ibge_municipios import get_nome_municipio_por_codigo, _load_ibge_municipios


class Command(BaseCommand):
    help = 'Lista codigo_municipio/UF da base CNPJ que não batem com o IBGE.'

    def add_arguments(self, parser):
        parser.add_argument('--uf', type=str, default=None, help='Filtrar por UF (ex: MG).')
        parser.add_argument('--saida', type=str, default=None, help='Salvar lista em arquivo (um código por linha).')

    def handle(self, *args, **options):
        _load_ibge_municipios()

        qs = (
            ImportacaoEstabelecimentoCNPJ.objects.exclude(codigo_municipio__isnull=True)
            .exclude(codigo_municipio='')
            .values_list('codigo_municipio', 'uf')
            .distinct()
        )
        if options.get('uf'):
            uf = (options['uf'] or '').strip().upper()[:2]
            qs = qs.filter(uf=uf)

        sem_ibge = []
        total = 0
        for cod, uf in qs:
            total += 1
            nome = get_nome_municipio_por_codigo(cod, uf=uf or None)
            if not nome:
                sem_ibge.append((cod, uf or ''))

        sem_ibge.sort(key=lambda x: (x[1], x[0]))
        self.stdout.write('Total de pares (codigo_municipio, UF) na base: %d' % total)
        self.stdout.write('Sem correspondência no IBGE: %d' % len(sem_ibge))

        if options.get('saida'):
            path = options['saida']
            with open(path, 'w', encoding='utf-8') as f:
                for cod, uf in sem_ibge:
                    f.write('%s\n' % cod)
            self.stdout.write(self.style.SUCCESS('Códigos gravados em: %s' % path))
        else:
            for cod, uf in sem_ibge[:200]:
                self.stdout.write('  %s (UF=%s)' % (cod, uf))
            if len(sem_ibge) > 200:
                self.stdout.write('  ... e mais %d (use --saida arquivo.txt para listar todos)' % (len(sem_ibge) - 200))
