"""
Análise M-10 para produção: diagnostica por que uma safra tem menos registros que o esperado.

Uso (rodar no ambiente de produção, ex. Railway):
  python manage.py analise_m10_producao 2025-07
  python manage.py analise_m10_producao 2025-07 --json
  python manage.py analise_m10_producao 2025-07 --amostra 50
  python manage.py analise_m10_producao 2025-07 --os-duplicadas  # detalhe O.S. compartilhadas

Ex.: Julho/2025 deveria ter 895 e mostra 854. O comando lista:
- Total vendas com data_instalacao no mês (qualquer status)
- INSTALADA + data_instalacao: com/sem O.S.
- **data_criacao no mês vs fora do mês** (ex.: 41 instaladas criadas em junho, instaladas em julho)
- **O.S. duplicadas**: mesma O.S., várias vendas -> só 1 ContratoM10 (unique). Quem "sobra" não é considerada.
- ContratoM10 no mês, faltando, não consideradas por O.S. duplicada.
"""
from __future__ import print_function

import json
from collections import defaultdict
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from dateutil.relativedelta import relativedelta

from crm_app.models import Venda, ContratoM10, SafraM10, StatusCRM


def parse_month(s):
    year, month = int(s[:4]), int(s[5:7])
    d0 = date(year, month, 1)
    d1 = d0 + relativedelta(months=1)
    return d0, d1


def _data_criacao_no_mes(v, inicio, fim):
    if not v.data_criacao:
        return False
    d = v.data_criacao.date() if hasattr(v.data_criacao, 'date') else v.data_criacao
    return inicio <= d < fim


class Command(BaseCommand):
    help = 'Analisa vendas vs M-10 por safra (para produção)'

    def add_arguments(self, parser):
        parser.add_argument('mes', help='Mês YYYY-MM (ex: 2025-07)')
        parser.add_argument('--json', action='store_true', help='Saída JSON')
        parser.add_argument('--amostra', type=int, default=30, help='Quantos "faltando" listar (default 30)')
        parser.add_argument('--os-duplicadas', action='store_true', help='Listar O.S. com mais de uma venda (instaladas no mês)')

    def handle(self, *args, **options):
        mes = options.get('mes')
        if not mes or len(mes) != 7 or mes[4] != '-':
            self.stdout.write(self.style.ERROR('Use: python manage.py analise_m10_producao YYYY-MM'))
            return

        inicio, fim = parse_month(mes)
        base = Venda.objects.filter(ativo=True)
        status_instalada = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='INSTALADA').first()
        if not status_instalada:
            self.stdout.write(self.style.ERROR('Status INSTALADA não encontrado.'))
            return

        q_mes = Q(data_instalacao__gte=inicio, data_instalacao__lt=fim)

        # 1) Vendas com data_instalacao no mês (qualquer status)
        vendas_mes = base.filter(data_instalacao__gte=inicio, data_instalacao__lt=fim)
        total_mes = vendas_mes.count()

        # 1b) Vendas com data_criacao no mês (qualquer status)
        vendas_criacao_mes = base.filter(
            data_criacao__date__gte=inicio,
            data_criacao__date__lt=fim,
        )
        total_criacao_mes = vendas_criacao_mes.count()

        # 2) Por status
        por_status = list(
            vendas_mes.values('status_esteira__nome')
            .annotate(n=Count('id'))
            .order_by('-n')
        )
        status_map = {r['status_esteira__nome'] or '(sem status)': r['n'] for r in por_status}

        # 3) INSTALADA + data_instalacao no mês
        instaladas = base.filter(status_esteira=status_instalada).filter(q_mes)
        n_instaladas = instaladas.count()
        com_os = instaladas.exclude(ordem_servico__isnull=True).exclude(ordem_servico='').count()
        sem_os = n_instaladas - com_os

        # 3b) INSTALADAS: data_criacao NO MÊS vs FORA DO MÊS (ex.: criou em junho, instalou em julho)
        instaladas_list = list(instaladas.only('id', 'ordem_servico', 'data_criacao', 'data_instalacao', 'status_esteira'))
        criacao_no_mes = sum(1 for v in instaladas_list if _data_criacao_no_mes(v, inicio, fim))
        criacao_fora_mes = n_instaladas - criacao_no_mes

        # Agrupar por O.S. (só com O.S. preenchida)
        os_to_vendas = defaultdict(list)
        for v in instaladas_list:
            if v.ordem_servico and str(v.ordem_servico).strip():
                os_to_vendas[v.ordem_servico].append(v)

        # 4) ContratoM10 com data_instalacao no mês (igual dashboard)
        contratos = ContratoM10.objects.filter(
            data_instalacao__gte=inicio,
            data_instalacao__lt=fim,
        )
        n_contratos = contratos.count()
        os_com_contrato = set(contratos.exclude(ordem_servico__isnull=True).exclude(ordem_servico='').values_list('ordem_servico', flat=True))
        venda_ids_com_contrato = set(contratos.exclude(venda_id__isnull=True).values_list('venda_id', flat=True))
        # OS -> venda_id do contrato (qual venda está "vinculada" ao ContratoM10)
        os_to_venda_contrato = {}
        for c in contratos.exclude(ordem_servico__isnull=True).exclude(ordem_servico='').exclude(venda_id__isnull=True):
            os_to_venda_contrato[c.ordem_servico] = c.venda_id

        # 5) Faltando: INSTALADA + data_instalacao no mês, sem ContratoM10 (sem O.S. ou O.S. sem contrato)
        # 6) Não consideradas por O.S. duplicada: tem O.S., existe contrato para essa O.S., mas o contrato
        #    está vinculado a OUTRA venda (ex.: criada em julho). Esta (criada em junho) "não é considerada".
        faltando = []
        nao_consideradas_os_duplicada = []
        for v in instaladas_list:
            if v.id in venda_ids_com_contrato:
                continue
            if not v.ordem_servico or not str(v.ordem_servico).strip():
                faltando.append({'id': v.id, 'os': None, 'motivo': 'sem O.S.', 'criacao_no_mes': _data_criacao_no_mes(v, inicio, fim)})
            elif v.ordem_servico not in os_com_contrato:
                faltando.append({'id': v.id, 'os': v.ordem_servico, 'motivo': 'sem contrato', 'criacao_no_mes': _data_criacao_no_mes(v, inicio, fim)})
            else:
                # O.S. tem contrato, mas vinculado a outra venda
                vid_linked = os_to_venda_contrato.get(v.ordem_servico)
                if vid_linked is not None and vid_linked != v.id:
                    nao_consideradas_os_duplicada.append({
                        'id': v.id,
                        'os': v.ordem_servico,
                        'venda_linked_no_contrato': vid_linked,
                        'criacao_no_mes': _data_criacao_no_mes(v, inicio, fim),
                    })

        # O.S. duplicadas (mais de uma venda com mesma O.S., instaladas no mês)
        os_duplicadas = [(os_, lst) for os_, lst in os_to_vendas.items() if len(lst) > 1]
        n_os_duplicadas = len(os_duplicadas)
        n_vendas_em_os_duplicada = sum(len(lst) for _, lst in os_duplicadas)

        amostra_n = min(options.get('amostra', 30), len(faltando))
        amostra = faltando[:amostra_n]

        # Amostra "não consideradas" (ex.: 41 criadas em junho, instaladas em julho)
        amostra_nao_consideradas = nao_consideradas_os_duplicada[: options.get('amostra', 30)]

        out = {
            'mes': mes,
            'data_inicio': str(inicio),
            'data_fim': str(fim),
            'vendas_data_instalacao_no_mes': total_mes,
            'vendas_data_criacao_no_mes': total_criacao_mes,
            'por_status': status_map,
            'instalada_data_instalacao_no_mes': n_instaladas,
            'instaladas_criacao_no_mes': criacao_no_mes,
            'instaladas_criacao_fora_mes': criacao_fora_mes,
            'instaladas_com_os': com_os,
            'instaladas_sem_os': sem_os,
            'contratos_m10_no_mes': n_contratos,
            'faltando_no_m10': len(faltando),
            'amostra_faltando': amostra,
            'nao_consideradas_os_duplicada': len(nao_consideradas_os_duplicada),
            'amostra_nao_consideradas': amostra_nao_consideradas,
            'os_duplicadas_count': n_os_duplicadas,
            'vendas_em_os_duplicada': n_vendas_em_os_duplicada,
        }
        if options.get('os_duplicadas') and os_duplicadas:
            detalhes = []
            for os_, lst in os_duplicadas[:50]:
                criacao_in = sum(1 for v in lst if _data_criacao_no_mes(v, inicio, fim))
                detalhes.append({
                    'os': os_,
                    'qtd_vendas': len(lst),
                    'venda_ids': [v.id for v in lst],
                    'criacao_no_mes': criacao_in,
                    'criacao_fora_mes': len(lst) - criacao_in,
                })
            out['os_duplicadas_detalhe'] = detalhes

        if options.get('json'):
            self.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
            return

        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('ANALISE M-10 PRODUCAO - {}'.format(mes)))
        self.stdout.write('=' * 70)
        self.stdout.write('Vendas com data_instalacao no mes (qualquer status): {}'.format(total_mes))
        self.stdout.write('Vendas com data_criacao no mes (qualquer status): {}'.format(total_criacao_mes))
        self.stdout.write('Por status (data_instalacao no mes): {}'.format(status_map))
        self.stdout.write('')
        self.stdout.write('INSTALADA + data_instalacao no mes: {}'.format(n_instaladas))
        self.stdout.write('  Com O.S.: {} | Sem O.S.: {}'.format(com_os, sem_os))
        self.stdout.write('  ** data_criacao NO MES: {} | data_criacao FORA DO MES: {} **'.format(criacao_no_mes, criacao_fora_mes))
        self.stdout.write('')
        self.stdout.write('ContratoM10 no mes (data_instalacao): {}'.format(n_contratos))
        self.stdout.write('')
        self.stdout.write('Faltando no M-10 (instaladas sem contrato): {}'.format(len(faltando)))
        for i, f in enumerate(amostra, 1):
            self.stdout.write('  {}  id={} os={} -> {} (criacao_no_mes={})'.format(
                i, f['id'], f['os'] or '-', f['motivo'], f.get('criacao_no_mes')
            ))
        if len(faltando) > amostra_n:
            self.stdout.write('  ... e mais {}'.format(len(faltando) - amostra_n))
        self.stdout.write('')
        self.stdout.write('Nao consideradas (O.S. duplicada; contrato vinculado a outra venda): {}'.format(len(nao_consideradas_os_duplicada)))
        for i, r in enumerate(amostra_nao_consideradas, 1):
            self.stdout.write('  {}  id={} os={} -> contrato em venda_id={} (criacao_no_mes={})'.format(
                i, r['id'], r['os'], r['venda_linked_no_contrato'], r['criacao_no_mes']
            ))
        if len(nao_consideradas_os_duplicada) > len(amostra_nao_consideradas):
            self.stdout.write('  ... e mais {}'.format(len(nao_consideradas_os_duplicada) - len(amostra_nao_consideradas)))
        self.stdout.write('')
        self.stdout.write('O.S. duplicadas (mesma O.S., varias vendas instaladas no mes): {} O.S. | {} vendas'.format(
            n_os_duplicadas, n_vendas_em_os_duplicada
        ))
        if options.get('os_duplicadas') and os_duplicadas:
            for d in out.get('os_duplicadas_detalhe', [])[:20]:
                self.stdout.write('  OS {}: {} vendas (ids {}); criacao_no_mes={} fora={}'.format(
                    d['os'], d['qtd_vendas'], d['venda_ids'], d['criacao_no_mes'], d['criacao_fora_mes']
                ))
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        if total_mes > 0 and n_instaladas < total_mes:
            self.stdout.write(self.style.WARNING(
                'Muitas vendas no mes tem status diferente de INSTALADA. M-10 so considera INSTALADA.'
            ))
        if total_criacao_mes > 0 and total_mes < total_criacao_mes:
            self.stdout.write(self.style.WARNING(
                'Ha mais vendas por data_criacao que por data_instalacao. '
                'M-10 usa data_instalacao. Corrija com corrigir_data_venda_legado --atualizar-instalacao se for o caso.'
            ))
        if criacao_fora_mes > 0:
            self.stdout.write(self.style.WARNING(
                '{} instaladas tem data_criacao FORA do mes (ex.: criou junho, instalou julho). '
                'Todas entram no M-10 por data_instalacao; se faltam registros, veja O.S. duplicadas.'.format(criacao_fora_mes)
            ))
        if len(nao_consideradas_os_duplicada) > 0:
            self.stdout.write(self.style.WARNING(
                'ContratoM10 exige 1 contrato por O.S. (unique). {} vendas instaladas no mes nao tem '
                'contrato proprio pois a O.S. ja tem contrato vinculado a outra venda. Use --os-duplicadas '
                'para detalhes.'.format(len(nao_consideradas_os_duplicada))
            ))
        if len(faltando) > 0:
            self.stdout.write(self.style.WARNING(
                'Rode "Popular safra" no Bonus M-10 ou: python manage.py reprocessar_vendas_m10.'
            ))
