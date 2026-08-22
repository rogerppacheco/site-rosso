# -*- coding: utf-8 -*-
r"""
Importa base CEP -> cidade para o banco local (tabela CepLocalidade).
Assim o sistema usa primeiro o banco e não depende só de API para preencher a cidade.

Onde baixar uma base (ex.: CEP Aberto, Base dos Dados):
  - CEP Aberto: https://www.cepaberto.com/ (cadastro gratuito, download por estado)
  - Base dos Dados DNE: https://basedosdados.org/dataset/9cb64a51-1a60-4162-8bc7-c86c1b6597a0

Formato do CSV esperado:
  - Cabeçalho na primeira linha.
  - Colunas (nomes aceitos): cep, CEP, codigo_postal | localidade, cidade, municipio, localidade | uf, UF, estado.
  - CEP pode ter traço ou só dígitos (será normalizado para 8 dígitos).
  - Separador: vírgula ou ponto-e-vírgula (detectado automaticamente).

Exemplo:
  cep,localidade,uf
  30130100,Belo Horizonte,MG

  ou

  CEP;cidade;UF
  30130-100;Belo Horizonte;MG

Uso:
  python manage.py importar_base_cep C:\Downloads\cep_mg.csv
  python manage.py importar_base_cep C:\Downloads\ceps.csv --separador ";"
  python manage.py importar_base_cep C:\Downloads\ceps.csv --limite 10000
"""
import csv
import os
import re
from django.core.management.base import BaseCommand
from django.db import transaction


def _normalizar_cep(val):
    s = re.sub(r'\D', '', str(val or ''))
    return s[:8] if len(s) >= 8 else (s.zfill(8) if len(s) == 7 else None)


class Command(BaseCommand):
    help = 'Importa CSV de CEP -> cidade para a tabela CepLocalidade (banco local).'

    def add_arguments(self, parser):
        parser.add_argument(
            'arquivo',
            type=str,
            help='Caminho do arquivo CSV (cabeçalho na primeira linha).',
        )
        parser.add_argument(
            '--separador',
            type=str,
            default='',
            help='Separador de colunas (ex: "," ou ";"). Se vazio, detecta automaticamente.',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=0,
            help='Máximo de linhas a importar (0 = todas).',
        )
        parser.add_argument(
            '--sobrescrever',
            action='store_true',
            help='Se informado, limpa a tabela CepLocalidade antes de importar.',
        )

    def handle(self, *args, **options):
        from crm_app.models import CepLocalidade

        arquivo = options['arquivo']
        if not os.path.isfile(arquivo):
            self.stdout.write(self.style.ERROR('Arquivo não encontrado: %s' % arquivo))
            return

        separador = options['separador']
        limite = options['limite'] or 0
        sobrescrever = options['sobrescrever']

        if sobrescrever:
            n = CepLocalidade.objects.count()
            CepLocalidade.objects.all().delete()
            self.stdout.write('Tabela CepLocalidade limpa (%d registros removidos).' % n)

        encoding_candidates = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        content = None
        for enc in encoding_candidates:
            try:
                with open(arquivo, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            self.stdout.write(self.style.ERROR('Não foi possível ler o arquivo com encodings comuns.'))
            return

        lines = content.strip().splitlines()
        if not lines:
            self.stdout.write(self.style.ERROR('Arquivo vazio.'))
            return

        # Detectar separador
        if not separador:
            first = lines[0]
            if ';' in first and first.count(';') >= 2:
                separador = ';'
            else:
                separador = ','
        reader = csv.DictReader(lines, delimiter=separador)
        fieldnames = list(reader.fieldnames or [])

        # Mapear colunas (aceita vários nomes)
        col_cep = None
        col_localidade = None
        col_uf = None
        for name in fieldnames:
            n = (name or '').strip().lower()
            if n in ('cep', 'cep_limpo', 'codigo_postal', 'codigo postal', 'postal_code'):
                col_cep = name
            elif n in ('localidade', 'cidade', 'municipio', 'município', 'city', 'nome_municipio'):
                col_localidade = name
            elif n in ('uf', 'estado', 'state', 'sigla_uf'):
                col_uf = name

        if not col_cep:
            col_cep = fieldnames[0] if fieldnames else None
        if not col_localidade:
            col_localidade = fieldnames[1] if len(fieldnames) > 1 else None
        if not col_uf:
            col_uf = fieldnames[2] if len(fieldnames) > 2 else None

        if not col_cep or not col_localidade:
            self.stdout.write(self.style.ERROR(
                'Colunas CEP e cidade/localidade não encontradas. Cabeçalho: %s' % fieldnames
            ))
            return

        criados = 0
        ignorados = 0
        batch = []
        BATCH_SIZE = 2000

        for i, row in enumerate(reader):
            if limite and (i + 1) > limite:
                break
            cep_raw = row.get(col_cep, '')
            loc = (row.get(col_localidade, '') or '').strip()[:255]
            uf = (row.get(col_uf, '') or '').strip().upper()[:2]

            cep = _normalizar_cep(cep_raw)
            if not cep or not loc:
                ignorados += 1
                continue

            batch.append({'cep': cep, 'localidade': loc, 'uf': uf or ''})
            if len(batch) >= BATCH_SIZE:
                criados += self._upsert_batch(CepLocalidade, batch)
                batch = []
            if (i + 1) % 50000 == 0:
                self.stdout.write('  %d linhas processadas...' % (i + 1))

        if batch:
            criados += self._upsert_batch(CepLocalidade, batch)

        self.stdout.write(self.style.SUCCESS(
            'Importação concluída. Inseridos/atualizados: %d | Ignorados: %d' % (criados, ignorados)
        ))
        self.stdout.write('Total na tabela CepLocalidade: %d' % CepLocalidade.objects.count())

    def _upsert_batch(self, model, batch):
        with transaction.atomic():
            created = 0
            for item in batch:
                _, was_created = model.objects.update_or_create(
                    cep=item['cep'],
                    defaults={'localidade': item['localidade'], 'uf': item['uf'] or ''}
                )
                if was_created:
                    created += 1
            return created
