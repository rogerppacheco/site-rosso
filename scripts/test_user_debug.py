#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from usuarios.models import Usuario
import json

user = Usuario.objects.get(username='admin')
print(f'User: {user.username}')
print(f'Password hash: {user.password[:50]}...')
print(f'Is active: {user.is_active}')
print(f'Check password (admin123): {user.check_password("admin123")}')

# Teste autenticação Django
from django.contrib.auth import authenticate
auth_user = authenticate(username='admin', password='admin123')
print(f'\nDjango authenticate result: {auth_user}')
if auth_user:
    print(f'  Username: {auth_user.username}')
    print(f'  Is active: {auth_user.is_active}')
