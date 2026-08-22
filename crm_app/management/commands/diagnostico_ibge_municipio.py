# -*- coding: utf-8 -*-
"""
Diagnóstico do cruzamento IBGE (código município -> nome).
Mostra amostras do banco e o resultado do lookup para conferir formato.
"""
from django.core.management.base import BaseCommand

from crm_app.models import ImportacaoEstabelecimentoCNPJ
from crm_app.ibge_municipios import get_nome_municipio_por_codigo, _get_data_path, _load_ibge_municipios
from crm_app.ibge_municipios import _IBGE_MAP
import os


class Command(BaseCommand):
    help = 'Diagnóstico do cruzamento IBGE: amostra codigo_municipio/UF do banco e resultado do lookup.'

    def handle(self, *args, **options):
        path = _get_data_path()
        self.stdout.write('Arquivo IBGE: %s' % path)
        self.stdout.write('Existe: %s' % os.path.isfile(path))
        _load_ibge_municipios()
        self.stdout.write('Mapa carregado: %d entradas' % (len(_IBGE_MAP) if _IBGE_MAP else 0))
        if not _IBGE_MAP:
            self.stdout.write(self.style.ERROR('Nenhum dado IBGE. Rode: python manage.py download_ibge_municipios'))
            return

        # Amostra do banco
        amostras = (
            ImportacaoEstabelecimentoCNPJ.objects.filter(situacao_cadastral='02')
            .exclude(codigo_municipio__isnull=True)
            .exclude(codigo_municipio='')
            .values('codigo_municipio', 'uf')[:20]
            .distinct()
        )
        self.stdout.write('')
        self.stdout.write('Amostra (codigo_municipio | uf | nome_municipio):')
        for a in amostras:
            cod = a.get('codigo_municipio') or ''
            uf = a.get('uf') or ''
            nome = get_nome_municipio_por_codigo(cod, uf=uf)
            self.stdout.write('  %r | %r | %s' % (cod, uf, nome or '(vazio)'))

        self.stdout.write('')
        self.stdout.write('Teste manual: 6200 + MG = %s' % get_nome_municipio_por_codigo('6200', uf='MG'))
        self.stdout.write('Teste manual: 316200 (6 dígitos) = %s' % get_nome_municipio_por_codigo('316200'))
