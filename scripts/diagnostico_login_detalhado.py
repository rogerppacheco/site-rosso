#!/usr/bin/env python
"""
Diagnóstico detalhado do erro 401 de login
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.contrib.auth import get_user_model, authenticate
from usuarios.models import Usuario

User = get_user_model()

print("=" * 80)
print("DIAGNÓSTICO DETALHADO DO ERRO 401")
print("=" * 80)

# 1. Verificar usuário 'admin'
print("\n[1] Verificar usuário 'admin':")
try:
    user = Usuario.objects.get(username='admin')
    print(f"  ✅ Usuário encontrado")
    print(f"     - ID: {user.id}")
    print(f"     - Username: {user.username}")
    print(f"     - Email: {user.email}")
    print(f"     - Is active: {user.is_active}")
    print(f"     - Is staff: {user.is_staff}")
    print(f"     - Password hash: {user.password[:30]}...")
except Usuario.DoesNotExist:
    print(f"  ❌ Usuário 'admin' não encontrado")
    sys.exit(1)

# 2. Testar autenticação com authenticate()
print("\n[2] Testar authenticate(username='admin', password='admin123'):")
auth_user = authenticate(username='admin', password='admin123')
if auth_user:
    print(f"  ✅ Autenticação SUCEDE")
    print(f"     - Usuário retornado: {auth_user.username}")
else:
    print(f"  ❌ Autenticação FALHA - retornou None")
    print(f"     Testando outras variações...")
    
    # Tentar com check_password direto
    print(f"\n[3] Testar check_password() direto:")
    if user.check_password('admin123'):
        print(f"  ✅ check_password SUCEDE para 'admin123'")
    else:
        print(f"  ❌ check_password FALHA para 'admin123'")
        print(f"     Tentando resetar a senha...")
        user.set_password('admin123')
        user.save()
        print(f"  ✅ Senha resetada")
        
        # Testar novamente
        if user.check_password('admin123'):
            print(f"  ✅ check_password SUCEDE após reset")
        else:
            print(f"  ❌ check_password FALHA após reset - PROBLEMA GRAVE!")

# 4. Testar TokenObtainPairSerializer
print("\n[4] Testar TokenObtainPairSerializer:")
from usuarios.serializers import CustomTokenObtainPairSerializer
from rest_framework.exceptions import ValidationError

serializer = CustomTokenObtainPairSerializer(data={
    'username': 'admin',
    'password': 'admin123'
})

if serializer.is_valid():
    print(f"  ✅ Serializer VÁLIDO")
    data = serializer.validated_data
    print(f"     - Token: {data.get('token', data.get('access', ''))[:50]}...")
else:
    print(f"  ❌ Serializer INVÁLIDO")
    print(f"     - Erros: {serializer.errors}")

print("\n" + "=" * 80)
print("RESUMO")
print("=" * 80)
if auth_user and serializer.is_valid():
    print("✅ LOGIN DEVE FUNCIONAR - tudo está correto")
else:
    print("❌ PROBLEMA IDENTIFICADO - veja os detalhes acima")
