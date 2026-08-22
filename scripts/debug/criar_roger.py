"""
Script para criar usuário Roger (debug/setup).
Uso (a partir da raiz do projeto): python scripts/debug/criar_roger.py
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from usuarios.models import Usuario

print("=== Criando usuário Roger ===")

try:
    user = Usuario.objects.get(username="Roger")
    print(f"User Roger já existe: {user.username}")
except Usuario.DoesNotExist:
    user = Usuario.objects.create_user(
        username="Roger",
        password="123456",
        first_name="Roger",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    print("✓ User Roger criado com sucesso!")
    print(f"  Username: {user.username}")
    print("  Senha: 123456")
    print(f"  Is active: {user.is_active}")
    print(f"  Is staff: {user.is_staff}")

from rest_framework.test import APIClient

client = APIClient()
response = client.post(
    "/api/auth/login/",
    {"username": "Roger", "password": "123456"},
    format="json",
)

print("\n=== Teste de Login ===")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    print("✓ Login bem sucedido!")
    print(f"Token: {response.data.get('token', 'N/A')[:50]}...")
else:
    print(f"✗ Erro: {response.data}")
