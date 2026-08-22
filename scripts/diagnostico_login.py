#!/usr/bin/env python
"""
Script para diagnosticar problemas de autenticação/login
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.contrib.auth import get_user_model
from usuarios.models import Usuario

User = get_user_model()

print("=" * 80)
print("DIAGNÓSTICO DE AUTENTICAÇÃO")
print("=" * 80)

# 1. Verificar usuários no banco
print("\n[1] Usuários no banco de dados:")
usuarios = Usuario.objects.all().values('id', 'username', 'email', 'is_active', 'is_staff')
if usuarios:
    for u in usuarios[:10]:
        print(f"  - ID: {u['id']}, Username: {u['username']}, Email: {u['email']}, Ativo: {u['is_active']}, Staff: {u['is_staff']}")
    if usuarios.count() > 10:
        print(f"  ... e mais {usuarios.count() - 10} usuários")
else:
    print("  ❌ NENHUM usuário encontrado no banco!")
    print("\n  Criando usuário de teste...")
    try:
        user = Usuario.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='admin123',
            is_superuser=True,
            is_staff=True
        )
        print(f"  ✅ Criado: username='admin', password='admin123'")
    except Exception as e:
        print(f"  ❌ Erro: {e}")

# 2. Testar autenticação manual
print("\n[2] Teste de autenticação manual:")
try:
    user = Usuario.objects.get(username='admin')
    print(f"  ✅ Usuário 'admin' encontrado")
    print(f"     - Email: {user.email}")
    print(f"     - Ativo: {user.is_active}")
    print(f"     - Senha válida: {user.check_password('admin123')}")
    
    if user.check_password('admin123'):
        print(f"  ✅ Senha 'admin123' está CORRETA")
    else:
        print(f"  ❌ Senha 'admin123' está INCORRETA")
except Usuario.DoesNotExist:
    print(f"  ❌ Usuário 'admin' NÃO encontrado")

# 3. Testar autenticação com email
print("\n[3] Teste com email:")
try:
    user = Usuario.objects.get(email__iexact='admin@test.com')
    print(f"  ✅ Usuário com email 'admin@test.com' encontrado: {user.username}")
except Usuario.DoesNotExist:
    print(f"  ❌ Nenhum usuário com email 'admin@test.com'")

# 4. Testar JWT token
print("\n[4] Teste de geração de JWT token:")
try:
    from rest_framework_simplejwt.tokens import RefreshToken
    user = Usuario.objects.get(username='admin')
    refresh = RefreshToken.for_user(user)
    print(f"  ✅ Token gerado com sucesso")
    print(f"     - Refresh: {str(refresh)[:50]}...")
    print(f"     - Access: {str(refresh.access_token)[:50]}...")
except Exception as e:
    print(f"  ❌ Erro ao gerar token: {e}")

# 5. Status geral
print("\n" + "=" * 80)
print("RESUMO:")
print("=" * 80)
print(f"Total de usuários: {Usuario.objects.count()}")
print(f"Usuários ativos: {Usuario.objects.filter(is_active=True).count()}")
print(f"Usuários staff: {Usuario.objects.filter(is_staff=True).count()}")

print("\n💡 PARA TESTAR LOGIN, USE:")
print("   URL: http://localhost:8000/api/auth/login/")
print("   Method: POST")
print("   Body: {\"username\": \"admin\", \"password\": \"admin123\"}")

print("\n" + "=" * 80)
