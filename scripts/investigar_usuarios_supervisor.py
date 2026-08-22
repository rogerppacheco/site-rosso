#!/usr/bin/env python
"""
Script para investigar usuários com supervisor que não aparecem na lista
"""
import os
import sys
import django

# Configurar Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from usuarios.models import Usuario

print("=" * 60)
print("INVESTIGAÇÃO: Usuários com Supervisor")
print("=" * 60)

# 1. Total de usuários com supervisor
usuarios_com_supervisor = Usuario.objects.filter(supervisor__isnull=False)
total_com_supervisor = usuarios_com_supervisor.count()
print(f"\n1. Total de usuários COM supervisor: {total_com_supervisor}")

# 2. Usuários ATIVOS com supervisor
ativos_com_supervisor = usuarios_com_supervisor.filter(is_active=True)
print(f"2. Usuários ATIVOS com supervisor: {ativos_com_supervisor.count()}")

# 3. Usuários INATIVOS com supervisor
inativos_com_supervisor = usuarios_com_supervisor.filter(is_active=False)
print(f"3. Usuários INATIVOS com supervisor: {inativos_com_supervisor.count()}")

# 4. Verificar se há usuários com supervisor inativo
supervisor_inativo = usuarios_com_supervisor.filter(supervisor__is_active=False)
print(f"4. Usuários cujo SUPERVISOR está inativo: {supervisor_inativo.count()}")

# 5. Exemplos de usuários inativos com supervisor
print("\n" + "-" * 60)
print("Exemplos de usuários INATIVOS com supervisor:")
print("-" * 60)
for u in inativos_com_supervisor[:10]:
    supervisor_nome = u.supervisor.username if u.supervisor else "N/A"
    supervisor_ativo = u.supervisor.is_active if u.supervisor else False
    print(f"  - {u.username} (ativo={u.is_active}, supervisor={supervisor_nome}, supervisor_ativo={supervisor_ativo})")

# 6. Verificar se há problemas com supervisor None mas que deveria ter
print("\n" + "-" * 60)
print("Verificando inconsistências...")
print("-" * 60)

# Verificar se há usuários que deveriam ter supervisor mas não têm
# (isso seria uma verificação de lógica de negócio)

# 7. Testar query que a API usa
print("\n" + "-" * 60)
print("Testando query da API (is_active=True):")
print("-" * 60)
api_query = Usuario.objects.filter(is_active=True).select_related('supervisor', 'perfil').prefetch_related('groups').order_by('first_name')
api_count = api_query.count()
print(f"Total retornado pela API (is_active=True): {api_count}")

# Verificar quantos desses têm supervisor
api_com_supervisor = api_query.filter(supervisor__isnull=False)
print(f"Desses, quantos têm supervisor: {api_com_supervisor.count()}")

# 8. Testar query com is_active=False
print("\n" + "-" * 60)
print("Testando query da API (is_active=False):")
print("-" * 60)
api_query_inativo = Usuario.objects.filter(is_active=False).select_related('supervisor', 'perfil').prefetch_related('groups').order_by('first_name')
api_count_inativo = api_query_inativo.count()
print(f"Total retornado pela API (is_active=False): {api_count_inativo}")

# Verificar quantos desses têm supervisor
api_inativo_com_supervisor = api_query_inativo.filter(supervisor__isnull=False)
print(f"Desses, quantos têm supervisor: {api_inativo_com_supervisor.count()}")

print("\n" + "=" * 60)
print("FIM DA INVESTIGAÇÃO")
print("=" * 60)
