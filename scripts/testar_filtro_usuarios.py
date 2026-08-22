#!/usr/bin/env python
"""
Script para testar se o filtro is_active está funcionando corretamente na API
"""
import os
import sys
import django

# Configurar Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from usuarios.models import Usuario
from django.test import RequestFactory
from usuarios.views import UsuarioViewSet
from django.contrib.auth import get_user_model

User = get_user_model()

print("=" * 60)
print("TESTE: Filtro is_active na API de Usuários")
print("=" * 60)

# Criar um usuário de teste para autenticação
try:
    test_user = User.objects.filter(is_superuser=True).first()
    if not test_user:
        print("ERRO: Nenhum superusuário encontrado para teste")
        sys.exit(1)
except Exception as e:
    print(f"ERRO ao buscar usuário: {e}")
    sys.exit(1)

# Criar factory de requests
factory = RequestFactory()

# Criar viewset
viewset = UsuarioViewSet()

# 1. Testar sem parâmetro is_active (deve retornar todos)
print("\n1. Testando SEM parâmetro is_active:")
request = factory.get('/usuarios/')
request.user = test_user
viewset.request = request
viewset.format_kwarg = None

queryset = viewset.get_queryset()
total = queryset.count()
com_supervisor = queryset.filter(supervisor__isnull=False).count()
print(f"   Total de usuários: {total}")
print(f"   Usuários com supervisor: {com_supervisor}")

# 2. Testar com is_active=True
print("\n2. Testando com is_active=True:")
request = factory.get('/usuarios/?is_active=true')
request.user = test_user
viewset.request = request

queryset = viewset.get_queryset()
total_ativos = queryset.count()
com_supervisor_ativos = queryset.filter(supervisor__isnull=False).count()
print(f"   Total de usuários ATIVOS: {total_ativos}")
print(f"   Usuários ATIVOS com supervisor: {com_supervisor_ativos}")

# Verificar se corresponde ao esperado
esperado_ativos = Usuario.objects.filter(is_active=True).count()
esperado_ativos_com_supervisor = Usuario.objects.filter(is_active=True, supervisor__isnull=False).count()
print(f"   Esperado (ativos): {esperado_ativos}")
print(f"   Esperado (ativos com supervisor): {esperado_ativos_com_supervisor}")

if total_ativos == esperado_ativos and com_supervisor_ativos == esperado_ativos_com_supervisor:
    print("   ✅ TESTE PASSOU!")
else:
    print("   ❌ TESTE FALHOU!")

# 3. Testar com is_active=False
print("\n3. Testando com is_active=False:")
request = factory.get('/usuarios/?is_active=false')
request.user = test_user
viewset.request = request

queryset = viewset.get_queryset()
total_inativos = queryset.count()
com_supervisor_inativos = queryset.filter(supervisor__isnull=False).count()
print(f"   Total de usuários INATIVOS: {total_inativos}")
print(f"   Usuários INATIVOS com supervisor: {com_supervisor_inativos}")

# Verificar se corresponde ao esperado
esperado_inativos = Usuario.objects.filter(is_active=False).count()
esperado_inativos_com_supervisor = Usuario.objects.filter(is_active=False, supervisor__isnull=False).count()
print(f"   Esperado (inativos): {esperado_inativos}")
print(f"   Esperado (inativos com supervisor): {esperado_inativos_com_supervisor}")

if total_inativos == esperado_inativos and com_supervisor_inativos == esperado_inativos_com_supervisor:
    print("   ✅ TESTE PASSOU!")
else:
    print("   ❌ TESTE FALHOU!")

# 4. Listar alguns exemplos de usuários inativos com supervisor
print("\n4. Exemplos de usuários INATIVOS com supervisor:")
inativos_com_supervisor = Usuario.objects.filter(is_active=False, supervisor__isnull=False)[:5]
for u in inativos_com_supervisor:
    print(f"   - {u.username} (supervisor: {u.supervisor.username if u.supervisor else 'N/A'})")

print("\n" + "=" * 60)
print("FIM DO TESTE")
print("=" * 60)
