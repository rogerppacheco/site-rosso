#!/usr/bin/env python
"""Contar registros no PostgreSQL Railway"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.apps import apps

print('\n📊 Registros no PostgreSQL Railway:\n')

total_geral = 0

for app_name in ['crm_app', 'usuarios', 'auth', 'admin']:
    try:
        app_config = apps.get_app_config(app_name)
        total_app = 0
        
        for model in app_config.get_models():
            count = model.objects.count()
            if count > 0:
                print(f'  {model.__name__}: {count:,}')
                total_app += count
        
        if total_app > 0:
            print(f'✅ {app_name}: {total_app:,} registros\n')
            total_geral += total_app
    except:
        pass

print(f'\n🎯 TOTAL GERAL: {total_geral:,} registros\n')
