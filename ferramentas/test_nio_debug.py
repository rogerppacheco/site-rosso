#!/usr/bin/env python
"""Script para testar consulta Nio e ver o JSON completo"""
import os
import sys
import django
import json

# Setup Django
sys.path.insert(0, 'c:/site-record')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.nio_api import consultar_dividas_nio

# CPF do Rodrigo Brenner
cpf = '12886868620'

print('='*80)
print(f'🔍 CONSULTANDO DÍVIDAS NIO PARA CPF: {cpf}')
print('='*80)

try:
    resultado = consultar_dividas_nio(cpf=cpf, limit=10)
    
    print('\n📊 RESULTADO BRUTO DA API (JSON COMPLETO):')
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    
    invoices = resultado.get('invoices', [])
    print(f'\n{"="*80}')
    print(f'📋 TOTAL DE FATURAS RETORNADAS: {len(invoices)}')
    print('='*80)
    
    for i, inv in enumerate(invoices, 1):
        print(f'\n{"─"*80}')
        print(f'FATURA #{i}')
        print(f'{"─"*80}')
        print(f'🏷️  Produto: {inv.get("product", "N/D")}')
        print(f'💰 Valor: R$ {inv.get("amount", 0)}')
        print(f'📅 Vencimento (raw): {inv.get("due_date_raw", "N/D")}')
        print(f'📅 Vencimento (expiration): {inv.get("expiration", "N/D")}')
        print(f'🔖 Status: {inv.get("status", "N/D")}')
        print(f'🔢 Deal Code: {inv.get("deal_code", "N/D")}')
        print(f'🆔 Debt ID: {inv.get("debt_id", "N/D")}')
        
        pix = inv.get('pix', '') or ''
        barras = inv.get('barcode', '') or ''
        
        print(f'\n📱 PIX (total: {len(pix)} caracteres):')
        print(f'   Primeiros 80: {pix[:80]}...' if len(pix) > 80 else f'   {pix}')
        
        print(f'\n📊 CÓDIGO DE BARRAS (total: {len(barras)} caracteres):')
        print(f'   Primeiros 80: {barras[:80]}...' if len(barras) > 80 else f'   {barras}')
        
except Exception as e:
    print(f'\n❌ ERRO: {str(e)}')
    import traceback
    traceback.print_exc()

print(f'\n{"="*80}')
print('✅ Consulta finalizada')
print('='*80)
