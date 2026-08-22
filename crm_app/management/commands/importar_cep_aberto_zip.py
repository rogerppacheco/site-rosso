# -*- coding: utf-8 -*-
r"""
Importa os CSVs dos zips do CEP Aberto (MG) para a tabela CepLocalidade.
Lê CEP, cidade e UF diretamente do CSV dentro de cada zip — não consulta ViaCEP/OpenCEP.

Se o CSV tiver cabeçalho com colunas como cep, cidade/localidade/municipio, uf/estado,
essas colunas são usadas. Caso não tenha cabeçalho, assume coluna 0 = CEP (cidade fica vazia).

Uso:
  python manage.py importar_cep_aberto_zip c:\downloads\mg.cepaberto_parte_1.zip ...
  python manage.py importar_cep_aberto_zip c:\downloads  (procura *.zip no diretório)
"""
import csv
import io
import os
import re
import zipfile
from django.core.management.base import BaseCommand


def _normalizar_cep(val):
    s = re.sub(r'\D', '', str(val or ''))
    return s[:8] if len(s) >= 8 else (s.zfill(8) if len(s) == 7 else None)


# Nomes de coluna aceitos para detectar cabeçalho (minúsculo)
CEP_HEADERS = ('cep', 'cep_limpo', 'codigo_postal', 'codigo postal', 'postal_code')
CIDADE_HEADERS = ('localidade', 'cidade', 'municipio', 'município', 'city', 'nome_municipio')
UF_HEADERS = ('uf', 'estado', 'state', 'sigla_uf')


def _detect_header_indices(first_row):
    """
    Se a primeira linha parecer cabeçalho, retorna (idx_cep, idx_cidade, idx_uf).
    idx_cidade ou idx_uf podem ser None se não encontrados.
    Caso não seja cabeçalho, retorna None.
    """
    if not first_row:
        return None
    row_lower = [(c or '').strip().lower() for c in first_row]
    idx_cep = None
    idx_cidade = None
    idx_uf = None
    for i, cell in enumerate(row_lower):
        if cell in CEP_HEADERS:
            idx_cep = i
        elif cell in CIDADE_HEADERS:
            idx_cidade = i
        elif cell in UF_HEADERS:
            idx_uf = i
    if idx_cep is None:
        return None
    return (idx_cep, idx_cidade, idx_uf)


def _read_csv_ceps(text, has_header, idx_cep, idx_cidade, idx_uf):
    """
    Lê o CSV (texto já decodificado) e retorna um dict cep -> (localidade, uf).
    Se has_header, a primeira linha é cabeçalho. idx_* são índices das colunas.
    """
    result = {}
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    start = 1 if has_header and rows else 0
    for row in rows[start:]:
        if not row or idx_cep >= len(row):
            continue
        cep = _normalizar_cep(row[idx_cep])
        if not cep:
            continue
        localidade = (row[idx_cidade].strip()[:255]) if idx_cidade is not None and idx_cidade < len(row) else ''
        uf = (row[idx_uf].strip().upper()[:2]) if idx_uf is not None and idx_uf < len(row) else ''
        result[cep] = (localidade, uf or 'MG')
    return result


class Command(BaseCommand):
    help = 'Importa zips do CEP Aberto: lê CEP e cidade dos CSVs e grava em CepLocalidade (sem API).'

    def add_arguments(self, parser):
        parser.add_argument(
            'caminhos',
            nargs='+',
            type=str,
            help='Caminhos dos .zip ou um diretório (serão listados *.zip).',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=0,
            help='Máximo de CEPs únicos a processar (0 = todos).',
        )

    def handle(self, *args, **options):
        from crm_app.models import CepLocalidade

        caminhos = options['caminhos']
        limite = options['limite'] or 0

        # Resolver: se um caminho for diretório, listar *.zip
        zips = []
        for p in caminhos:
            p = os.path.abspath(p)
            if os.path.isfile(p) and p.lower().endswith('.zip'):
                zips.append(p)
            elif os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    if f.lower().endswith('.zip'):
                        zips.append(os.path.join(p, f))

        if not zips:
            self.stdout.write(self.style.ERROR('Nenhum arquivo .zip encontrado.'))
            return

        self.stdout.write('Zips a processar: %d' % len(zips))

        # Ler todos os CSVs e montar cep -> (localidade, uf) a partir dos arquivos
        cep_dados = {}  # cep -> (localidade, uf)
        for zip_path in zips:
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    names = [n for n in z.namelist() if n.lower().endswith('.csv')]
                    if not names:
                        self.stdout.write(self.style.WARNING('  Sem CSV em %s' % zip_path))
                        continue
                    for name in names:
                        raw = z.read(name)
                        for enc in ('utf-8', 'latin-1', 'cp1252'):
                            try:
                                text = raw.decode(enc)
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            text = raw.decode('latin-1', errors='ignore')

                        lines = text.strip().splitlines()
                        if not lines:
                            continue
                        first_row = next(csv.reader(io.StringIO(lines[0])))
                        header_info = _detect_header_indices(first_row)

                        if header_info:
                            idx_cep, idx_cidade, idx_uf = header_info
                            self.stdout.write('  Cabeçalho detectado: CEP col %d, cidade col %s, UF col %s' % (
                                idx_cep, idx_cidade, idx_uf
                            ))
                            dados = _read_csv_ceps(text, True, idx_cep, idx_cidade, idx_uf)
                        else:
                            # Sem cabeçalho: só coluna 0 = CEP, cidade vazia
                            dados = _read_csv_ceps(text, False, 0, None, None)

                        for cep, (loc, uf) in dados.items():
                            if cep and (cep not in cep_dados or cep_dados[cep][0]):
                                # Só sobrescreve se já tiver cidade no arquivo (prioriza dado completo)
                                if not cep_dados.get(cep) or loc:
                                    cep_dados[cep] = (loc, uf or 'MG')

            except Exception as e:
                self.stdout.write(self.style.ERROR('  Erro em %s: %s' % (zip_path, e)))

        ceps_ordenados = sorted(cep_dados.keys())
        if limite:
            ceps_ordenados = ceps_ordenados[:limite]
        self.stdout.write('CEPs únicos nos arquivos: %d' % len(ceps_ordenados))

        # Carregar o que já está no banco
        self.stdout.write('Carregando CEPs já existentes no banco...')
        ceps_no_banco = set(CepLocalidade.objects.values_list('cep', flat=True))

        # Só inserir os que ainda não estão
        batch = []
        BATCH_SIZE = 5000
        inseridos = 0
        sem_cidade = 0
        ja_existentes = 0
        for cep in ceps_ordenados:
            if cep in ceps_no_banco:
                ja_existentes += 1
                continue
            localidade, uf = cep_dados[cep]
            if not localidade:
                sem_cidade += 1
            batch.append(CepLocalidade(cep=cep, localidade=localidade or '', uf=uf or 'MG'))
            if len(batch) >= BATCH_SIZE:
                CepLocalidade.objects.bulk_create(batch)
                inseridos += len(batch)
                self.stdout.write('  Inseridos %d...' % inseridos)
                batch = []

        if batch:
            CepLocalidade.objects.bulk_create(batch)
            inseridos += len(batch)

        self.stdout.write(self.style.SUCCESS(
            'Concluído. Inseridos: %d | Já existentes (ignorados): %d | Sem cidade no CSV: %d' % (
                inseridos, ja_existentes, sem_cidade
            )
        ))
        self.stdout.write('Total na tabela CepLocalidade: %d' % CepLocalidade.objects.count())
