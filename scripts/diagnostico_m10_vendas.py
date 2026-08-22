#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Diagnóstico: vendas INSTALADA vs Bônus M-10 por mês.

Explica por que o CRM pode mostrar mais "Instalados" que o Bônus M-10 na mesma safra.
Ex.: Janeiro/26: 364 instalados no CRM vs 341 no M-10.

Motivos:
  1. CRM filtra por (data_criacao OU data_instalacao) no período; M-10 usa SOMENTE
     data_instalacao no mês. Vendas "criadas" em Jan mas instaladas em Dez contam
     no CRM para Jan e no M-10 para Dez.
  2. M-10 exige ordem_servico; sem O.S. não vira ContratoM10.
  3. O.S. duplicada: várias vendas mesma O.S. -> 1 contrato (M-10 é por O.S.).

Uso:
  python scripts/diagnostico_m10_vendas.py 2026-01
  python scripts/diagnostico_m10_vendas.py 2025-07
  python scripts/diagnostico_m10_vendas.py 2026-01 --inicio 2026-01-01 --fim 2026-01-25
  python scripts/diagnostico_m10_vendas.py 2025-07 --por-status   # Jul/25: INSTALADA vs outros status
"""
from __future__ import print_function

import os
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from dateutil.relativedelta import relativedelta
from django.db.models import Q, Count
from crm_app.models import Venda, ContratoM10, SafraM10, StatusCRM


def parse_month(s):
    """YYYY-MM -> (data_inicio, fim_mes_exclusive) do mês."""
    year, month = int(s[:4]), int(s[5:7])
    d0 = date(year, month, 1)
    d1 = d0 + relativedelta(months=1)
    return d0, d1


def run(mes_ref, data_inicio=None, data_fim=None, por_status=False):
    # Período M-10 = mês inteiro
    inicio_m10, fim_m10 = parse_month(mes_ref)
    safra_str = mes_ref  # YYYY-MM

    # Período CRM (se não informado, usa mês inteiro)
    if data_inicio and data_fim:
        dt_ini = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        dt_fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
    else:
        dt_ini = inicio_m10
        dt_fim = fim_m10 + relativedelta(days=-1)  # último dia do mês

    # Range: [dt_ini, dt_fim] inclusivo. Upper para __lt = dt_fim + 1.
    dt_fim_upper = dt_fim + timedelta(days=1)

    base = Venda.objects.filter(ativo=True)
    status_instalada = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='INSTALADA').first()
    if not status_instalada:
        print('Erro: status INSTALADA não encontrado em StatusCRM (tipo=Esteira).')
        return 1

    print('=' * 70)
    print('DIAGNÓSTICO M-10 vs VENDAS INSTALADAS')
    print('=' * 70)
    print('Mês ref (safra M-10):', mes_ref, '| Período CRM:', dt_ini, 'a', dt_fim)
    print()

    # ---- 1. Por status (opcional, ex.: Jul/25) ----
    if por_status:
        print('--- Vendas por STATUS (data_criacao ou data_instalacao no periodo) ---')
        q_periodo = Q(data_criacao__date__gte=dt_ini, data_criacao__date__lt=dt_fim_upper) | \
                    Q(data_instalacao__gte=dt_ini, data_instalacao__lt=dt_fim_upper)
        agg = list(base.filter(q_periodo).values('status_esteira__nome').annotate(
            total=Count('id')
        ).order_by('-total'))
        for r in agg:
            nome = r['status_esteira__nome'] or '(sem status)'
            print('  {}: {}'.format(nome, r['total']))
        if not agg:
            print('  (nenhuma venda no periodo)')
        inst = base.filter(q_periodo, status_esteira=status_instalada).count()
        print('  -> INSTALADA (nesse periodo):', inst)
        print()

    # ---- 2. Contagem estilo CRM: INSTALADA + (data_criacao OU data_instalacao) no período ----
    q_crm = Q(data_criacao__date__gte=dt_ini, data_criacao__date__lt=dt_fim_upper) | \
            Q(data_instalacao__gte=dt_ini, data_instalacao__lt=dt_fim_upper)
    crm_instalados = base.filter(
        status_esteira=status_instalada
    ).filter(q_crm).count()
    print('CRM-like (Instalados):  INSTALADA + (data_criacao OU data_instalacao) no período')
    print('  Total:', crm_instalados)
    print()

    # ---- 3. Vendas com data_instalacao no mês (qualquer status) ----
    vendas_mes_qualquer = base.filter(data_instalacao__gte=inicio_m10, data_instalacao__lt=fim_m10)
    total_mes_qualquer = vendas_mes_qualquer.count()
    print('Vendas com data_instalacao no mês (qualquer status):', total_mes_qualquer)
    print()

    # ---- 4. Contagem estilo M-10: INSTALADA + data_instalacao no mês da safra ----
    q_m10 = Q(data_instalacao__gte=inicio_m10, data_instalacao__lt=fim_m10)
    vendas_m10 = base.filter(status_esteira=status_instalada).filter(q_m10)
    total_m10_vendas = vendas_m10.count()
    com_os = vendas_m10.exclude(ordem_servico__isnull=True).exclude(ordem_servico='').count()
    sem_os = total_m10_vendas - com_os

    print('M-10-like (safra):      INSTALADA + data_instalacao no mês', mes_ref)
    print('  Total vendas:', total_m10_vendas)
    print('  Com O.S.:   ', com_os)
    print('  Sem O.S.:   ', sem_os)
    print()

    # ---- 5. ContratoM10 na safra (por data_instalacao, igual ao dashboard) ----
    contratos_safra = ContratoM10.objects.filter(
        data_instalacao__gte=inicio_m10,
        data_instalacao__lt=fim_m10,
    )
    total_m10 = contratos_safra.count()
    print('Bônus M-10 (safra {}):  ContratoM10 com data_instalacao no mês'.format(mes_ref))
    print('  Total contratos:', total_m10)
    print()

    # ---- 6. Diferença CRM vs M-10 ----
    print('--- DIFERENÇA CRM vs M-10 ---')
    diff = crm_instalados - total_m10
    if diff > 0:
        print('CRM tem {} a mais que M-10. Possíveis motivos:'.format(diff))
        print('  1. CRM usa data_criacao OU data_instalacao; M-10 usa SO data_instalacao.')
        print('     -> Vendas "criadas" no periodo mas instaladas em outro mes entram no CRM e nao na safra.')
        print('  2. Vendas INSTALADA com data_instalacao no mes mas SEM O.S. -> nao viram ContratoM10.')
        print('  3. O.S. duplicada: varias vendas mesma O.S. -> 1 contrato so (M-10 e por O.S.).')
    elif diff < 0:
        print('M-10 tem {} a mais que CRM. Possivel: periodo CRM (inicio/fim) menor que o mes.'.format(-diff))
    else:
        print('Contagens iguais.')
    print()

    # ---- 7. Quem falta no M-10 (tem data_instalacao no mês, INSTALADA, mas sem contrato) ----
    print('--- FALTANDO NO M-10 (INSTALADA + data_instalacao no mês, sem ContratoM10) ---')
    os_com_contrato = set(
        contratos_safra.exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
        .values_list('ordem_servico', flat=True)
    )
    venda_ids_com_contrato = set(contratos_safra.exclude(venda_id__isnull=True).values_list('venda_id', flat=True))
    faltando = []
    for v in vendas_m10.only('id', 'ordem_servico', 'data_criacao', 'data_instalacao'):
        if v.id in venda_ids_com_contrato:
            continue
        if not v.ordem_servico or not str(v.ordem_servico).strip():
            faltando.append((v, 'sem O.S.'))
        elif v.ordem_servico not in os_com_contrato:
            faltando.append((v, 'sem contrato'))
    print('Total faltando:', len(faltando))
    for v, motivo in faltando[:30]:
        dc = v.data_criacao.date() if v.data_criacao else None
        di = v.data_instalacao
        print('  id={} OS={} data_criacao={} data_instalacao={} -> {}'.format(
            v.id, v.ordem_servico or '-', dc, di, motivo))
    if len(faltando) > 30:
        print('  ... e mais', len(faltando) - 30)
    print()

    # ---- 8. No CRM mas data_instalacao fora do mês (ou null) ----
    print('--- NO CRM "Instalados" MAS data_instalacao FORA do mês (ou vazia) ---')
    no_crm_fora_m10 = base.filter(
        status_esteira=status_instalada
    ).filter(q_crm).exclude(
        data_instalacao__gte=inicio_m10,
        data_instalacao__lt=fim_m10
    )
    n_fora = no_crm_fora_m10.count()
    print('Total (contam no CRM, não na safra):', n_fora)
    for v in no_crm_fora_m10.only('id', 'ordem_servico', 'data_criacao', 'data_instalacao')[:20]:
        dc = v.data_criacao.date() if v.data_criacao else None
        di = v.data_instalacao
        print('  id={} OS={} data_criacao={} data_instalacao={}'.format(v.id, v.ordem_servico or '-', dc, di))
    if n_fora > 20:
        print('  ... e mais', n_fora - 20)
    print()

    # ---- 9. O.S. duplicadas (mesma O.S., mais de uma venda INSTALADA no mês) ----
    duplicadas = (
        vendas_m10.exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico='')
        .values('ordem_servico')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
    )
    n_dup = list(duplicadas)
    if n_dup:
        print('--- O.S. DUPLICADAS (mais de 1 venda INSTALADA no mês com mesma O.S.) ---')
        for r in n_dup[:15]:
            print('  OS {}: {} vendas'.format(r['ordem_servico'], r['n']))
        if len(n_dup) > 15:
            print('  ... e mais', len(n_dup) - 15)
        print('  -> M-10 tem 1 contrato por O.S.; multiplas vendas mesma O.S. = 1 contrato.')
    print()
    print('=' * 70)
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Diagnóstico M-10 vs vendas instaladas')
    ap.add_argument('mes', help='Mês YYYY-MM (ex: 2026-01, 2025-07)')
    ap.add_argument('--inicio', help='Data início período CRM (YYYY-MM-DD)')
    ap.add_argument('--fim', help='Data fim período CRM (YYYY-MM-DD)')
    ap.add_argument('--por-status', action='store_true', help='Listar vendas por status (ex.: Jul/25)')
    args = ap.parse_args()
    return run(args.mes, args.inicio, args.fim, args.por_status)


if __name__ == '__main__':
    sys.exit(main() or 0)
