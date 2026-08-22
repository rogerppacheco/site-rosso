#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Corrige apenas data_instalacao de vendas a partir de um CSV com OS e DATA_INSTALACAO.

Use quando a instalação foi preenchida incorretamente (ex.: igual à data de criação).
Não altera data_criacao nem data_pedido.

CSV: colunas OS e DATA_INSTALACAO (separador tab ou vírgula). Data DD/MM/YYYY.

Uso:
  python scripts/atualizar_data_instalacao_por_os.py --arquivo corrigir_instalacao.csv
  python scripts/atualizar_data_instalacao_por_os.py --arquivo corrigir_instalacao.csv --dry-run

Também atualiza ContratoM10 (safra, data_instalacao) quando existir contrato com essa OS.
"""
from __future__ import print_function

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from django.utils import timezone
from crm_app.models import Venda, ContratoM10, SafraM10


def parse_date(s):
    s = (s or '').strip()
    if not s:
        return None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_os(os_val):
    s = str(os_val or '').strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s


def load_csv(path):
    """Carrega [(os, data_instalacao), ...] do CSV. Cabeçalho: OS, DATA_INSTALACAO."""
    rows = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines:
        return rows
    sep = '\t' if '\t' in lines[0] else ','
    parts0 = [p.strip().upper() for p in lines[0].split(sep)]
    idx_os = idx_dt = None
    for i, p in enumerate(parts0):
        if p == 'OS':
            idx_os = i
        if 'DATA' in p and 'INSTALACAO' in p:
            idx_dt = i
    if idx_os is None:
        idx_os = 0
    if idx_dt is None:
        idx_dt = 1
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(sep)]
        if len(cols) <= max(idx_os, idx_dt):
            continue
        os_val = normalize_os(cols[idx_os])
        dt = parse_date(cols[idx_dt])
        if os_val and dt:
            rows.append((os_val, dt))
    return rows


def find_vendas_by_os(os_val):
    """Tenta ordem_servico exato; se não achar, tenta sem prefixo 'N-' (ex. 4-210432948964 -> 210432948964)."""
    qs = Venda.objects.filter(ativo=True, ordem_servico=os_val)
    if qs.exists():
        return qs
    if '-' in os_val:
        candidato = os_val.split('-', 1)[1].strip()
        if candidato:
            return Venda.objects.filter(ativo=True, ordem_servico=candidato)
    return Venda.objects.none()


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Corrige data_instalacao por OS (CSV: OS, DATA_INSTALACAO)')
    ap.add_argument('--arquivo', '-a', required=True, help='CSV com colunas OS e DATA_INSTALACAO')
    ap.add_argument('--dry-run', action='store_true', help='Apenas simular')
    args = ap.parse_args()

    if not os.path.isfile(args.arquivo):
        print('Arquivo nao encontrado:', args.arquivo)
        return 1

    rows = load_csv(args.arquivo)
    print('Linhas carregadas:', len(rows))
    if not rows:
        print('Nenhum registro.')
        return 0

    updated = 0
    not_found = 0
    errors = 0

    for os_val, dt in rows:
        try:
            qs = find_vendas_by_os(os_val)
            n = qs.count()
            if n == 0:
                not_found += 1
                print('  Nao encontrado OS:', os_val)
                continue
            if not args.dry_run:
                os_list = list(qs.values_list('ordem_servico', flat=True).distinct())
                qs.update(data_instalacao=dt)
                safra_str = dt.strftime('%Y-%m')
                mes_ref = dt.replace(day=1)
                SafraM10.objects.get_or_create(
                    mes_referencia=mes_ref,
                    defaults={'total_instalados': 0, 'total_ativos': 0, 'total_elegivel_bonus': 0, 'valor_bonus_total': 0}
                )
                for o in os_list:
                    if o:
                        ContratoM10.objects.filter(ordem_servico=o).update(data_instalacao=dt, safra=safra_str)
            updated += n
            print('  OK OS:', os_val, '->', dt.strftime('%d/%m/%Y'), '({} venda(s))'.format(n))
        except Exception as e:
            errors += 1
            print('  Erro OS:', os_val, '|', e)

    print()
    print('=' * 60)
    print('RESUMO')
    print('=' * 60)
    print('Vendas atualizadas (data_instalacao):', updated)
    print('OS nao encontradas:', not_found)
    print('Erros:', errors)
    if args.dry_run:
        print('(dry-run: nenhuma alteracao)')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
