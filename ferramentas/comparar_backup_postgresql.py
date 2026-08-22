#!/usr/bin/env python
"""
COMPARADOR BACKUP vs POSTGRESQL
Identifica exatamente o que falta migrar e onde parou
"""
import os
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.apps import apps

print("="*70)
print("🔍 COMPARANDO BACKUP vs POSTGRESQL")
print("="*70)

def contar_no_backup(arquivos):
    """Conta registros por modelo nos arquivos de backup"""
    contagem_backup = {}
    
    for arquivo in arquivos:
        if not os.path.exists(arquivo):
            print(f"⚠️  {arquivo} não encontrado")
            continue
            
        print(f"\n📖 Lendo {arquivo}...")
        with open(arquivo, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        for item in data:
            model_name = item['model']  # Ex: 'crm_app.venda'
            contagem_backup[model_name] = contagem_backup.get(model_name, 0) + 1
    
    return contagem_backup

def contar_no_postgresql():
    """Conta registros por modelo no PostgreSQL"""
    contagem_pg = {}
    
    for app_name in ['usuarios', 'crm_app', 'osab', 'presenca', 'relatorios', 'core', 'auth', 'contenttypes', 'admin', 'sessions']:
        try:
            app_config = apps.get_app_config(app_name)
            for model in app_config.get_models():
                count = model.objects.count()
                model_key = f"{app_name}.{model.__name__.lower()}"
                contagem_pg[model_key] = count
        except:
            pass
    
    return contagem_pg

# Lê os backups
arquivos = [
    'backup_parte1_users.json',
    'backup_parte2_outros.json',
    'backup_parte3_crm.json'
]

backup_counts = contar_no_backup(arquivos)
pg_counts = contar_no_postgresql()

print("\n" + "="*70)
print("📊 COMPARAÇÃO DETALHADA")
print("="*70)

# Agrupa por arquivo de origem
faltando_total = 0
completos = []
incompletos = []

for model_name in sorted(backup_counts.keys()):
    backup_qty = backup_counts[model_name]
    pg_qty = pg_counts.get(model_name, 0)
    
    diferenca = backup_qty - pg_qty
    percentual = (pg_qty / backup_qty * 100) if backup_qty > 0 else 0
    
    if diferenca == 0:
        completos.append(model_name)
    else:
        incompletos.append({
            'modelo': model_name,
            'backup': backup_qty,
            'postgresql': pg_qty,
            'faltando': diferenca,
            'percentual': percentual
        })
        faltando_total += diferenca

# Mostra os incompletos primeiro (mais importante)
if incompletos:
    print("\n❌ MODELOS INCOMPLETOS (FALTANDO DADOS):")
    print(f"{'Modelo':<35} {'Backup':>10} {'PostgreSQL':>12} {'Faltando':>10} {'%':>6}")
    print("-" * 75)
    
    for item in sorted(incompletos, key=lambda x: x['faltando'], reverse=True):
        status = "⚠️ " if item['percentual'] > 50 else "❌"
        print(f"{status} {item['modelo']:<33} {item['backup']:>10,} {item['postgresql']:>12,} {item['faltando']:>10,} {item['percentual']:>5.1f}%")
    
    print(f"\n🔴 TOTAL FALTANDO: {faltando_total:,} registros")

# Mostra quais arquivos precisam ser reimportados
print("\n" + "="*70)
print("📋 AÇÃO NECESSÁRIA:")
print("="*70)

# Verifica arquivo por arquivo
parte1_incompleto = any('usuarios' in m['modelo'] or 'auth' in m['modelo'] for m in incompletos)
parte2_incompleto = any(any(app in m['modelo'] for app in ['osab', 'presenca', 'relatorios', 'core']) for m in incompletos)
parte3_incompleto = any('crm_app' in m['modelo'] for m in incompletos)

if parte1_incompleto:
    print("❌ backup_parte1_users.json PRECISA SER REIMPORTADO")
if parte2_incompleto:
    print("❌ backup_parte2_outros.json PRECISA SER REIMPORTADO")
if parte3_incompleto:
    print("❌ backup_parte3_crm.json PRECISA SER REIMPORTADO (parou no meio)")
    
    # Mostra onde parou
    crm_incompletos = [i for i in incompletos if 'crm_app' in i['modelo']]
    if crm_incompletos:
        print("\n📍 ONDE PAROU NO CRM:")
        for item in crm_incompletos[:5]:  # Mostra os 5 primeiros
            print(f"   - {item['modelo']}: {item['postgresql']:,}/{item['backup']:,} ({item['percentual']:.1f}%)")

if not incompletos:
    print("✅ TODOS OS DADOS FORAM MIGRADOS COM SUCESSO!")
    print(f"📊 Total: {sum(backup_counts.values()):,} registros")

print("\n" + "="*70)
