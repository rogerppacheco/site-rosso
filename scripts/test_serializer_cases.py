#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from rest_framework.test import APIClient

client = APIClient()

# Teste 1: Credenciais corretas
print("=== Teste 1: Corretas (admin/admin123) ===")
response = client.post('/api/auth/login/', {'username': 'admin', 'password': 'admin123'}, format='json')
print(f"Status: {response.status_code}")
if response.status_code == 200:
    print("✓ Login bem sucedido!")
else:
    print(f"✗ Erro: {response.data}")

# Teste 2: Senha errada
print("\n=== Teste 2: Errada (admin/senha_errada) ===")
response = client.post('/api/auth/login/', {'username': 'admin', 'password': 'senha_errada'}, format='json')
print(f"Status: {response.status_code}")
print(f"Response: {response.data}")

# Teste 3: Usuário não existe
print("\n=== Teste 3: Usuário não existe ===")
response = client.post('/api/auth/login/', {'username': 'naoexiste', 'password': 'qualquer'}, format='json')
print(f"Status: {response.status_code}")
print(f"Response: {response.data}")
