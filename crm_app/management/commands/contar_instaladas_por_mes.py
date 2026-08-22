"""
Consulta quantas vendas INSTALADA aparecem no CRM para cada mês que existe no sistema.

Regra CRM: status INSTALADA e (data_criacao no mês OU data_instalacao no mês).
Também exibe instaladas só por data_instalacao no mês (estilo M-10) para comparação.

Por que CRM != dt_inst?
  - CRM: entra no mês se data_criacao OU data_instalacao está no mês. Uma venda pode
    aparecer em 2 meses (ex.: criada junho, instalada julho -> conta em junho e julho).
  - dt_inst: só data_instalacao no mês. Cada venda entra no máximo em 1 mês.
  - Quando CRM > dt_inst: há vendas com data_criacao no mês mas data_instalacao em outro
    (ex.: criou em jan, instalou em dez). O CRM mostra em jan; dt_inst só em dez.

Uso (produção):
  python manage.py contar_instaladas_por_mes
  python manage.py contar_instaladas_por_mes --json
  python manage.py contar_instaladas_por_mes --inicio 2025-01 --fim 2026-12
  python manage.py contar_instaladas_por_mes --listar 2025-06   # lista vendas do mês (id, OS, dt_criacao, dt_inst)
"""
from __future__ import print_function

import json
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from django.db.models.functions import TruncMonth
from dateutil.relativedelta import relativedelta

from crm_app.models import Venda, StatusCRM


def parse_month(s):
    """YYYY-MM -> (date inicio, date fim)"""
    y, m = int(s[:4]), int(s[5:7])
    d0 = date(y, m, 1)
    d1 = d0 + relativedelta(months=1)
    return d0, d1


class Command(BaseCommand):
    help = 'Conta vendas INSTALADA por mês (como no CRM) para cada mês existente no sistema'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Saída JSON')
        parser.add_argument('--inicio', default=None, help='Mês inicial YYYY-MM (opcional)')
        parser.add_argument('--fim', default=None, help='Mês final YYYY-MM (opcional)')
        parser.add_argument('--listar', default=None, metavar='YYYY-MM', help='Lista vendas do mês (id, OS, dt_criacao, dt_inst)')

    def handle(self, *args, **options):
        status_instalada = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='INSTALADA').first()
        if not status_instalada:
            self.stdout.write(self.style.ERROR('Status INSTALADA não encontrado.'))
            return

        base = Venda.objects.filter(ativo=True, status_esteira=status_instalada)

        if options.get('listar'):
            self._listar_mes(base, options['listar'])
            return

        def _month_date(m):
            if hasattr(m, 'date') and callable(getattr(m, 'date')):
                m = m.date()
            return date(m.year, m.month, 1)

        # Meses que existem: union de (data_criacao) e (data_instalacao)
        meses_data_criacao = set(
            base.exclude(data_criacao__isnull=True)
            .annotate(mes=TruncMonth('data_criacao'))
            .values_list('mes', flat=True)
            .distinct()
        )
        meses_data_inst = set(
            base.exclude(data_instalacao__isnull=True)
            .annotate(mes=TruncMonth('data_instalacao'))
            .values_list('mes', flat=True)
            .distinct()
        )
        todos_meses = sorted(set(_month_date(m) for m in (meses_data_criacao | meses_data_inst)))

        if not todos_meses:
            self.stdout.write('Nenhum mês encontrado com vendas INSTALADA.')
            return

        # Filtrar por --inicio / --fim se informados
        if options.get('inicio'):
            try:
                d_ini, _ = parse_month(options['inicio'])
                todos_meses = [m for m in todos_meses if m >= d_ini]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('--inicio inválido. Use YYYY-MM.'))
                return
        if options.get('fim'):
            try:
                _, d_fim = parse_month(options['fim'])
                todos_meses = [m for m in todos_meses if m < d_fim]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('--fim inválido. Use YYYY-MM.'))
                return

        if not todos_meses:
            self.stdout.write('Nenhum mês no intervalo informado.')
            return

        rows = []
        for mes_ref in todos_meses:
            inicio = mes_ref
            fim = inicio + relativedelta(months=1)

            # CRM: INSTALADA com (data_criacao no mês OU data_instalacao no mês)
            q_crm = (
                (Q(data_criacao__date__gte=inicio) & Q(data_criacao__date__lt=fim))
                | (Q(data_instalacao__gte=inicio) & Q(data_instalacao__lt=fim))
            )
            n_crm = base.filter(q_crm).count()

            # Só data_instalacao no mês (estilo M-10)
            n_inst = base.filter(
                data_instalacao__gte=inicio,
                data_instalacao__lt=fim,
            ).count()

            rows.append({
                'mes': inicio.strftime('%Y-%m'),
                'mes_label': inicio.strftime('%m/%Y'),
                'instaladas_crm': n_crm,
                'instaladas_data_instalacao': n_inst,
            })

        out = {
            'meses': rows,
            'total_meses': len(rows),
        }

        if options.get('json'):
            self.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
            return

        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('VENDAS INSTALADA POR MES (como no CRM)'))
        self.stdout.write('Regra CRM: status INSTALADA e (data_criacao OU data_instalacao) no mes.')
        self.stdout.write('dt_inst: so data_instalacao no mes. CRM > dt_inst quando ha criacao no mes e instalacao em outro.')
        self.stdout.write('')
        self.stdout.write('{:<10} {:>18} {:>22}'.format(
            'Mes', 'Instaladas (CRM)', 'Instaladas (dt_inst)'
        ))
        self.stdout.write('-' * 52)
        for r in rows:
            self.stdout.write('{:<10} {:>18} {:>22}'.format(
                r['mes_label'],
                r['instaladas_crm'],
                r['instaladas_data_instalacao'],
            ))
        self.stdout.write('-' * 52)
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('')

    def _listar_mes(self, base, mes_str):
        if len(mes_str) != 7 or mes_str[4] != '-':
            self.stdout.write(self.style.ERROR('--listar: use YYYY-MM (ex: 2025-06).'))
            return
        inicio, fim = parse_month(mes_str)
        q_crm = (
            (Q(data_criacao__date__gte=inicio) & Q(data_criacao__date__lt=fim))
            | (Q(data_instalacao__gte=inicio) & Q(data_instalacao__lt=fim))
        )
        vendas = list(
            base.filter(q_crm)
            .only('id', 'ordem_servico', 'data_criacao', 'data_instalacao')
            .order_by('data_instalacao', 'data_criacao')
        )
        self.stdout.write('')
        self.stdout.write('INSTALADAS que contam para {} (CRM: data_criacao OU data_instalacao no mes)'.format(mes_str))
        self.stdout.write('Total: {}'.format(len(vendas)))
        self.stdout.write('')
        self.stdout.write('{:<8} {:<14} {:<12} {:<12} {}'.format(
            'id', 'OS', 'dt_criacao', 'dt_inst', 'conta_por'
        ))
        self.stdout.write('-' * 60)
        for v in vendas:
            dc = v.data_criacao.date() if v.data_criacao else None
            di = v.data_instalacao
            criacao_no_mes = dc and inicio <= dc < fim
            inst_no_mes = di and inicio <= di < fim
            if criacao_no_mes and inst_no_mes:
                conta = 'ambos'
            elif inst_no_mes:
                conta = 'dt_inst'
            else:
                conta = 'dt_criacao'
            self.stdout.write('{:<8} {:<14} {:<12} {:<12} {}'.format(
                v.id,
                (v.ordem_servico or '-')[:14],
                dc.strftime('%Y-%m-%d') if dc else '-',
                di.strftime('%Y-%m-%d') if di else '-',
                conta,
            ))
        self.stdout.write('')
        self.stdout.write('conta_por: dt_inst = so data_instalacao no mes | dt_criacao = so data_criacao | ambos')
        self.stdout.write('Se voce corrigiu instalacao para jul/25 e ainda aparecem com dt_inst em jun/25,')
        self.stdout.write('rode corrigir_data_venda_legado --atualizar-instalacao com CSV (DATA_VENDA, OS) em julho.')
        self.stdout.write('')
