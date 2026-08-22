# -*- coding: utf-8 -*-
r"""
Preenche o campo nome_municipio dos estabelecimentos CNPJ usando CepLocalidade (e IBGE como fallback).
Cruza CEP -> cidade para a base de condomínios de MG (ou outros filtros).

Uso:
  # Condomínios de MG (CNAE 8112500) - cruzar município por CEP
  python manage.py preencher_municipio_cep_cnpj --uf MG --cnae 8112500

  # Apenas registros que ainda estão sem nome_municipio
  python manage.py preencher_municipio_cep_cnpj --uf MG --cnae 8112500 --somente-vazios

  # Limite para teste
  python manage.py preencher_municipio_cep_cnpj --uf MG --cnae 8112500 --limite 1000
"""
import re
from django.core.management.base import BaseCommand
from django.db.models import Q


def _normalizar_cep(val):
    s = re.sub(r'\D', '', str(val or ''))
    return s[:8] if len(s) >= 8 else (s.zfill(8) if len(s) == 7 else None)


class Command(BaseCommand):
    help = 'Preenche nome_municipio na base CNPJ a partir de CepLocalidade (e IBGE quando CEP não estiver na base).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--uf',
            type=str,
            default='MG',
            help='UF dos estabelecimentos (default MG).',
        )
        parser.add_argument(
            '--cnae',
            type=str,
            default='8112500',
            help='CNAE fiscal (default 8112500 = condomínios). Use vazio para todos.',
        )
        parser.add_argument(
            '--somente-vazios',
            action='store_true',
            help='Atualizar apenas registros em que nome_municipio está vazio.',
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=0,
            help='Máximo de registros a processar (0 = todos).',
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=3000,
            help='Tamanho do lote para bulk_update (default 3000).',
        )

    def handle(self, *args, **options):
        from crm_app.models import ImportacaoEstabelecimentoCNPJ, CepLocalidade
        from crm_app.ibge_municipios import get_nome_municipio_por_codigo

        uf = (options.get('uf') or 'MG').strip().upper()[:2]
        cnae = (options.get('cnae') or '').strip().zfill(7)
        somente_vazios = options.get('somente_vazios', False)
        limite = options.get('limite') or 0
        batch_size = max(500, min(10000, options.get('batch') or 3000))

        qs = ImportacaoEstabelecimentoCNPJ.objects.filter(uf=uf)
        if cnae:
            qs = qs.filter(cnae_fiscal=cnae)
        if somente_vazios:
            qs = qs.filter(Q(nome_municipio__isnull=True) | Q(nome_municipio=''))
        total = qs.count()
        self.stdout.write('Registros a processar (UF=%s, CNAE=%s): %d' % (uf, cnae or 'todos', total))

        if total == 0:
            self.stdout.write('Nada a fazer.')
            return

        self.stdout.write('Carregando CepLocalidade...')
        cep_to_localidade = dict(CepLocalidade.objects.values_list('cep', 'localidade'))
        self.stdout.write('  %d CEPs na base CepLocalidade.' % len(cep_to_localidade))

        atualizados = 0
        sem_cep = 0
        sem_cidade = 0
        offset = 0

        while True:
            chunk = list(
                qs.order_by('id')
                .values_list('id', 'cep', 'codigo_municipio', 'uf', 'nome_municipio')
                [offset:offset + batch_size]
            )
            if not chunk:
                break
            if limite and (atualizados + len(chunk)) > limite:
                chunk = chunk[:limite - atualizados]
                if not chunk:
                    break

            ids_to_update = []
            new_names = {}
            for pk, cep, cod_mun, uf_val, nome_atual in chunk:
                cep_limpo = _normalizar_cep(cep)
                nome = None
                if cep_limpo:
                    nome = (cep_to_localidade.get(cep_limpo) or '').strip() or None
                if not nome and cod_mun:
                    nome = get_nome_municipio_por_codigo(cod_mun, uf=uf_val or uf)
                if not nome:
                    if not cep_limpo:
                        sem_cep += 1
                    else:
                        sem_cidade += 1
                if nome and nome != nome_atual:
                    ids_to_update.append(pk)
                    new_names[pk] = nome

            if ids_to_update:
                objs = ImportacaoEstabelecimentoCNPJ.objects.filter(pk__in=ids_to_update)
                for obj in objs:
                    obj.nome_municipio = new_names.get(obj.pk) or ''
                ImportacaoEstabelecimentoCNPJ.objects.bulk_update(objs, ['nome_municipio'], batch_size=2000)
                atualizados += len(ids_to_update)

            offset += len(chunk)
            if (offset // batch_size) % 5 == 0 and offset > 0:
                self.stdout.write('  Processados %d...' % min(offset, limite or offset))
            if limite and atualizados >= limite:
                break
            if len(chunk) < batch_size:
                break

        self.stdout.write(self.style.SUCCESS(
            'Concluído. Atualizados: %d | Sem CEP: %d | CEP sem cidade na base: %d' % (
                atualizados, sem_cep, sem_cidade
            )
        ))
