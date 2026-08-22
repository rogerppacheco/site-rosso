# -*- coding: utf-8 -*-
"""
Baixa a lista de municípios do IBGE e salva em crm_app/data/ibge_municipios.json.
Assim a coluna "Município" no export CNPJ passa a ter o nome da cidade sem depender da API em tempo de execução.

Uso:
    python manage.py download_ibge_municipios
"""
import json
import urllib.request
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Baixa municípios do IBGE e salva em crm_app/data/ibge_municipios.json'

    def handle(self, *args, **options):
        from crm_app.ibge_municipios import _get_data_path, _load_from_api
        import os

        self.stdout.write('Baixando municípios do IBGE...')
        data = _load_from_api()
        if not data:
            self.stderr.write(self.style.ERROR('Falha ao baixar da API do IBGE. Tente novamente mais tarde.'))
            return
        path = _get_data_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        self.stdout.write(self.style.SUCCESS(f'Salvo: {path} ({len(data)} municípios)'))
        self.stdout.write('A coluna "Município" no export CNPJ passará a usar esse arquivo.')
