#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Corrige data_pedido e data_criacao (DATA_VENDA) de vendas importadas via Legado que ficaram com data de hoje.
O CRM de Vendas exibe a coluna DATA usando data_criacao; ambos são atualizados.

Uso:
  python scripts/corrigir_data_venda_legado.py
  python scripts/corrigir_data_venda_legado.py --arquivo path/to/dados.csv
  python scripts/corrigir_data_venda_legado.py --dry-run
  python scripts/corrigir_data_venda_legado.py --atualizar-instalacao   # também corrige data_instalacao e ContratoM10 (Bônus M-10)

Primeiro gere o CSV (se ainda não existir):
  python scripts/_gerar_csv_jul25.py

CSV: colunas DATA_VENDA e OS (separador tab ou vírgula). Data no formato DD/MM/YYYY.
Rode no mesmo ambiente (local/Railway) em que a importação legado foi feita.

Bônus M-10: a safra "Julho/2025" usa data_instalacao (mês da instalação). Use --atualizar-instalacao
para alinhar data_instalacao = DATA_VENDA e atualizar ContratoM10. Só entram no M-10 vendas com
status_esteira = INSTALADA; rode reprocessar_vendas_m10 depois se criou novas instaladas.
"""
from __future__ import print_function

import os
import sys
import argparse
from datetime import datetime

# Django setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from django.utils import timezone
from crm_app.models import Venda, ContratoM10, SafraM10


def parse_date(s):
    """DD/MM/YYYY -> date. Retorna None se inválido."""
    s = (s or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%d/%m/%Y').date()
    except ValueError:
        return None


def normalize_os(os_val):
    """Mesmo tratamento do import legado: strip, remove .0 no fim."""
    s = str(os_val or '').strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s


def load_csv(path):
    """Carrega [(data, os), ...] do CSV. Primeira linha = cabeçalho."""
    rows = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines:
        return rows
    # Detectar separador
    sep = '\t' if '\t' in lines[0] else ','
    parts0 = [p.strip().upper() for p in lines[0].split(sep)]
    idx_date = idx_os = None
    for i, p in enumerate(parts0):
        if 'DATA' in p and 'VENDA' in p:
            idx_date = i
        if p == 'OS':
            idx_os = i
    if idx_date is None:
        idx_date = 0
    if idx_os is None:
        idx_os = 1
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(sep)]
        if len(cols) <= max(idx_date, idx_os):
            continue
        dt = parse_date(cols[idx_date])
        os_val = normalize_os(cols[idx_os])
        if dt and os_val:
            rows.append((dt, os_val))
    return rows


def main():
    ap = argparse.ArgumentParser(description='Corrige DATA_VENDA de vendas legado por OS')
    ap.add_argument('--arquivo', '-a', default=None, help='CSV com colunas DATA_VENDA e OS')
    ap.add_argument('--dry-run', action='store_true', help='Apenas simular, não alterar banco')
    ap.add_argument('--atualizar-instalacao', action='store_true', help='Também define data_instalacao=DATA_VENDA e atualiza ContratoM10 (safra) para Bônus M-10')
    args = ap.parse_args()

    path = args.arquivo
    if not path:
        path = os.path.join(os.path.dirname(__file__), 'corrigir_data_venda_legado_jul25.csv')
    if not os.path.isfile(path):
        print('Arquivo não encontrado:', path)
        print('Use --arquivo path/to/seu.csv ou coloque corrigir_data_venda_legado_jul25.csv em scripts/')
        return 1

    rows = load_csv(path)
    print('Linhas carregadas:', len(rows))
    if not rows:
        print('Nenhum registro para processar.')
        return 0

    updated = 0
    not_found = 0
    errors = 0
    exemplos = 0

    for dt, os_val in rows:
        try:
            qs = Venda.objects.filter(ordem_servico=os_val)
            n = qs.count()
            if n == 0:
                not_found += 1
                if not_found <= 5:
                    print('  Não encontrado OS:', os_val, '| DATA_VENDA:', dt.strftime('%d/%m/%Y'))
                continue
            # datetime à meia-noite, timezone-aware
            dt_midnight = timezone.make_aware(datetime.combine(dt, datetime.min.time()))
            if not args.dry_run:
                upd = {'data_pedido': dt_midnight, 'data_criacao': dt_midnight}
                if args.atualizar_instalacao:
                    upd['data_instalacao'] = dt
                qs.update(**upd)
                if args.atualizar_instalacao:
                    safra_str = dt.strftime('%Y-%m')
                    mes_ref = dt.replace(day=1)
                    SafraM10.objects.get_or_create(
                        mes_referencia=mes_ref,
                        defaults={'total_instalados': 0, 'total_ativos': 0, 'total_elegivel_bonus': 0, 'valor_bonus_total': 0}
                    )
                    ContratoM10.objects.filter(ordem_servico=os_val).update(data_instalacao=dt, safra=safra_str)
            updated += n
            exemplos += 1
            if exemplos <= 5:
                print('  OK OS:', os_val, '->', dt.strftime('%d/%m/%Y'), f'({n} venda(s))')
        except Exception as e:
            errors += 1
            print('  Erro OS:', os_val, '|', e)

    print()
    print('=' * 60)
    print('RESUMO')
    print('=' * 60)
    print('Atualizadas:', updated)
    print('OS não encontradas:', not_found)
    print('Erros:', errors)
    if args.dry_run:
        print('(dry-run: nenhuma alteração feita)')
    else:
        print('Correções aplicadas.')
        if args.atualizar_instalacao:
            print('Com --atualizar-instalacao: rode em seguida "python manage.py reprocessar_vendas_m10"')
            print('para criar ContratoM10 nas vendas INSTALADA que ainda não têm.')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
