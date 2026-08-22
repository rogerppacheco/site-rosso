#!/usr/bin/env python
"""
Verifica o estado da migração PostgreSQL
Mostra quais dados já foram importados e qual o último registro de cada tabela
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.apps import apps
from django.db import connection

print("="*70)
print("🔍 VERIFICANDO ESTADO DA MIGRAÇÃO POSTGRESQL")
print("="*70)

def verificar_app(app_name):
    try:
        app_config = apps.get_app_config(app_name)
        models = app_config.get_models()
        
        total_app = 0
        modelos_com_dados = []
        
        for model in models:
            count = model.objects.count()
            if count > 0:
                # Pega o último ID inserido
                try:
                    ultimo = model.objects.latest('id')
                    ultimo_id = ultimo.id
                except:
                    ultimo_id = "N/A"
                
                modelos_com_dados.append({
                    'nome': model.__name__,
                    'count': count,
                    'ultimo_id': ultimo_id
                })
                total_app += count
        
        if modelos_com_dados:
            print(f"\n📦 APP: {app_name.upper()}")
            print(f"{'Modelo':<30} {'Registros':>12} {'Último ID':>12}")
            print("-" * 55)
            
            for modelo in sorted(modelos_com_dados, key=lambda x: x['count'], reverse=True):
                print(f"{modelo['nome']:<30} {modelo['count']:>12,} {str(modelo['ultimo_id']):>12}")
            
            print(f"{'TOTAL ' + app_name.upper():<30} {total_app:>12,}")
            return total_app
        else:
            print(f"\n⚠️  APP {app_name}: SEM DADOS")
            return 0
            
    except Exception as e:
        print(f"❌ Erro ao verificar {app_name}: {e}")
        return 0

# Verifica cada app do projeto
total_geral = 0
apps_para_verificar = ['usuarios', 'crm_app', 'osab', 'presenca', 'relatorios', 'core', 'auth']

for app in apps_para_verificar:
    total_geral += verificar_app(app)

print("\n" + "="*70)
print(f"🎯 TOTAL GERAL: {total_geral:,} registros no PostgreSQL")
print("="*70)

# Verifica também quantas tabelas existem no banco
with connection.cursor() as cursor:
    cursor.execute("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
    """)
    num_tabelas = cursor.fetchone()[0]
    print(f"\n📊 Total de tabelas criadas: {num_tabelas}")
