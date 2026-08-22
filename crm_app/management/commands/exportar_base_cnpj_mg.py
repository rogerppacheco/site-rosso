# -*- coding: utf-8 -*-
r"""
Gera arquivo (Excel ou CSV) da base CNPJ por linha de comando, sem passar pelo site.
Recomendado para bases grandes (ex.: todos estabelecimentos de MG ou CNAE condomínios).

Exemplos:
  # Condomínios (CNAE 8112500) de MG -> Excel
  python manage.py exportar_base_cnpj_mg --uf MG --cnae 8112500 --arquivo C:\Downloads\cnpj_condominios_mg.xlsx

  # Todos estabelecimentos de MG (até o limite)
  python manage.py exportar_base_cnpj_mg --uf MG --arquivo C:\Downloads\cnpj_mg.xlsx --limite 100000

  # CSV em vez de Excel
  python manage.py exportar_base_cnpj_mg --uf MG --cnae 8112500 --formato csv --arquivo C:\Downloads\cnpj_mg.csv
"""
import csv
import os
import logging
import time
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def _normalize_numero(num):
    if num is None:
        return None
    s = str(num).strip().split("(")[0].strip()
    digits = ''.join(c for c in s if c.isdigit())
    return digits if digits else None


def _build_dfv_map_cep_fachada(pares_cep_num):
    if not pares_cep_num:
        return {}, {}
    from crm_app.models import DFV
    ceps_norm = {p[0] for p in pares_cep_num if p[0]}
    dfv_map_cep_num = {}
    dfv_map_cep_only = {}
    try:
        from django.db.models.functions import Replace
        from django.db.models import Value
        qs_dfv = DFV.objects.annotate(
            cep_limpo=Replace(Replace('cep', Value('-'), Value('')), Value(' '), Value(''))
        ).filter(cep_limpo__in=ceps_norm)
        for dfv_row in qs_dfv.values_list('cep_limpo', 'num_fachada', 'tipo_viabilidade'):
            cl = (dfv_row[0] or '').strip()
            num_f = _normalize_numero(dfv_row[1])
            tv = (dfv_row[2] or '').strip()
            if not cl:
                continue
            key = (cl, num_f)
            if key not in dfv_map_cep_num or ('VIAVEL' in tv.upper() or 'VIÁVEL' in tv.upper()):
                dfv_map_cep_num[key] = tv or '-'
            if cl not in dfv_map_cep_only or ('VIAVEL' in tv.upper() or 'VIÁVEL' in tv.upper()):
                dfv_map_cep_only[cl] = tv or '-'
    except Exception:
        for row in DFV.objects.filter(cep__in=ceps_norm).values_list('cep', 'num_fachada', 'tipo_viabilidade'):
            cl = ''.join(c for c in (row[0] or '') if c.isdigit())[:8]
            num_f = _normalize_numero(row[1])
            tv = (row[2] or '').strip()
            if not cl:
                continue
            key = (cl, num_f)
            if key not in dfv_map_cep_num or ('VIAVEL' in tv.upper() or 'VIÁVEL' in tv.upper()):
                dfv_map_cep_num[key] = tv or '-'
            if cl not in dfv_map_cep_only or ('VIAVEL' in tv.upper() or 'VIÁVEL' in tv.upper()):
                dfv_map_cep_only[cl] = tv or '-'
    return dfv_map_cep_num, dfv_map_cep_only


def _get_retorno_viab(cep_limpo, numero, dfv_map_cep_num, dfv_map_cep_only):
    num_limpo = _normalize_numero(numero)
    if cep_limpo:
        key = (cep_limpo, num_limpo)
        if key in dfv_map_cep_num:
            return dfv_map_cep_num[key]
        return dfv_map_cep_only.get(cep_limpo, '-')
    return '-'


class Command(BaseCommand):
    help = 'Exporta base CNPJ (estabelecimentos) para Excel ou CSV por linha de comando (ex.: MG, CNAE condomínios).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--uf',
            type=str,
            default='MG',
            help='UF (ex: MG). Pode repetir para várias UFs no futuro; por ora uma só.',
        )
        parser.add_argument(
            '--cnae',
            type=str,
            default='8112500',
            help='CNAE fiscal principal (ex: 8112500 = condomínios). Use vazio para todos os CNAEs.',
        )
        parser.add_argument(
            '--arquivo',
            type=str,
            default=None,
            help='Caminho do arquivo de saída (ex: C:\\Downloads\\cnpj_mg.xlsx). Obrigatório.',
        )
        parser.add_argument(
            '--formato',
            type=str,
            choices=['xlsx', 'csv'],
            default='xlsx',
            help='Formato de saída: xlsx ou csv.',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=100000,
            help='Máximo de registros a exportar (default 100000).',
        )
        parser.add_argument(
            '--todos-cnae',
            action='store_true',
            help='Se informado, exporta todos os CNAEs da UF (ignora --cnae).',
        )
        parser.add_argument(
            '--preencher-cidade-por-cep',
            action='store_true',
            help='Consulta ViaCEP para preencher Município quando o IBGE não achar. Usa para TODOS os CEPs (pode demorar).',
        )

    def handle(self, *args, **options):
        from crm_app.models import ImportacaoEstabelecimentoCNPJ
        from crm_app.ibge_municipios import get_nome_municipio_por_codigo
        from crm_app.services.cep_lookup import get_municipio_por_cep

        uf = (options.get('uf') or 'MG').strip().upper()[:2]
        cnae_arg = (options.get('cnae') or '').strip()
        if options.get('todos_cnae'):
            cnaes = []
        else:
            cnaes = [c.strip().zfill(7) for c in cnae_arg.split(',') if c.strip()] if cnae_arg else ['8112500']
        arquivo = options.get('arquivo')
        formato = (options.get('formato') or 'xlsx').lower()
        limite = max(1, min(500000, options.get('limite') or 100000))
        preencher_cidade_por_cep = options.get('preencher_cidade_por_cep', False)

        if not arquivo:
            self.stdout.write(self.style.ERROR('Informe --arquivo com o caminho do arquivo de saída.'))
            return

        qs = ImportacaoEstabelecimentoCNPJ.objects.filter(situacao_cadastral='02').filter(uf=uf)
        if cnaes:
            qs = qs.filter(cnae_fiscal__in=cnaes)
        total = qs.count()
        self.stdout.write('Total de registros (UF=%s, CNAE=%s): %d' % (uf, cnaes or 'todos', total))

        rows_list = list(
            qs.order_by('bairro', 'nome_fantasia')
            .values_list(
                'cnpj_completo', 'nome_fantasia', 'logradouro', 'numero', 'bairro', 'cep', 'uf', 'codigo_municipio',
                'nome_municipio',
                'ddd_telefone_1', 'telefone_1', 'email', 'cnae_fiscal', 'situacao_cadastral'
            )[:limite]
        )
        self.stdout.write('Exportando %d linhas...' % len(rows_list))

        pares_cep_num = set()
        for row in rows_list:
            c = ''.join(x for x in (row[5] or '') if x.isdigit())[:8]
            n = _normalize_numero(row[3])
            if c:
                pares_cep_num.add((c, n))
        self.stdout.write('Montando mapa DFV (viabilidade)...')
        dfv_map_cep_num, dfv_map_cep_only = _build_dfv_map_cep_fachada(pares_cep_num)

        cache_cep_municipio = {}
        viacep_limit = 10**6 if preencher_cidade_por_cep else 500
        if preencher_cidade_por_cep:
            self.stdout.write('Preenchimento de município por CEP (ViaCEP) ativado para todos os registros.')
        headers = [
            'CNPJ', 'Nome Fantasia', 'Logradouro', 'Numero', 'Bairro', 'CEP', 'UF', 'Cod.Municipio', 'Município',
            'Telefone', 'Email', 'CNAE', 'Situacao', 'Retorno Viabilidade (DFV)'
        ]

        if formato == 'xlsx':
            import openpyxl
            self.stdout.write('Gerando planilha Excel (pode demorar alguns minutos para 50k+ linhas)...')
            self.stdout.flush()
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Estabelecimentos'
            ws.append(headers)
            for i, row in enumerate(rows_list):
                if (i + 1) % 3000 == 0:
                    self.stdout.write('  %d / %d linhas...' % (i + 1, len(rows_list)))
                    self.stdout.flush()
                # row: ... index 8 = nome_municipio, 9-10 = ddd/telefone, 11 = email, 12 = cnae, 13 = situacao
                nome_mun = (row[8] or '').strip()
                if not nome_mun:
                    nome_mun = get_nome_municipio_por_codigo(row[7], uf=row[6]) or ''
                if not nome_mun:
                    cep_limpo = ''.join(x for x in (row[5] or '') if x.isdigit())[:8]
                    if cep_limpo and len(cache_cep_municipio) < viacep_limit:
                        if preencher_cidade_por_cep and cep_limpo not in cache_cep_municipio:
                            time.sleep(0.15)
                        nome_mun = get_municipio_por_cep(cep_limpo, cache=cache_cep_municipio) or ''
                cep_limpo = ''.join(x for x in (row[5] or '') if x.isdigit())[:8]
                retorno_viab = _get_retorno_viab(cep_limpo, row[3], dfv_map_cep_num, dfv_map_cep_only)
                ddd, tel = row[9], row[10]
                telefone = f"{ddd or ''}{tel or ''}".strip()
                ws.append(list(row[:7]) + [row[7]] + [nome_mun] + [telefone] + list(row[11:14]) + [retorno_viab])
            self.stdout.write('  Gravando arquivo no disco (pode demorar 1-2 min)...')
            self.stdout.flush()
            d = os.path.dirname(os.path.abspath(arquivo))
            if d:
                os.makedirs(d, exist_ok=True)
            wb.save(arquivo)
        else:
            d = os.path.dirname(os.path.abspath(arquivo))
            if d:
                os.makedirs(d, exist_ok=True)
            with open(arquivo, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(headers)
                for i, row in enumerate(rows_list):
                    if (i + 1) % 3000 == 0:
                        self.stdout.write('  %d / %d linhas...' % (i + 1, len(rows_list)))
                        self.stdout.flush()
                    nome_mun = (row[8] or '').strip()
                    if not nome_mun:
                        nome_mun = get_nome_municipio_por_codigo(row[7], uf=row[6]) or ''
                    if not nome_mun:
                        cep_limpo = ''.join(x for x in (row[5] or '') if x.isdigit())[:8]
                        if cep_limpo and len(cache_cep_municipio) < viacep_limit:
                            if preencher_cidade_por_cep and cep_limpo not in cache_cep_municipio:
                                time.sleep(0.15)
                            nome_mun = get_municipio_por_cep(cep_limpo, cache=cache_cep_municipio) or ''
                    cep_limpo = ''.join(x for x in (row[5] or '') if x.isdigit())[:8]
                    retorno_viab = _get_retorno_viab(cep_limpo, row[3], dfv_map_cep_num, dfv_map_cep_only)
                    ddd, tel = row[9], row[10]
                    out = list(row[:7]) + [row[7]] + [nome_mun] + [f"{ddd or ''}{tel or ''}".strip()] + list(row[11:14]) + [retorno_viab]
                    writer.writerow([(c or '') for c in out])

        self.stdout.write(self.style.SUCCESS('Arquivo gerado: %s (%d linhas)' % (arquivo, len(rows_list))))
