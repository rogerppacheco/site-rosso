#!/usr/bin/env python
"""
Script de diagnóstico para identificar queries lentas e N+1 problems
Executa em desenvolvimento e produção
"""
import os
import sys
import django
from django.conf import settings
from django.db import connection, reset_queries
from django.test.utils import override_settings

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import connection
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory
from crm_app.models import Venda, Usuario, StatusCRM
from crm_app.views import VendaViewSet
from crm_app.serializers import VendaSerializer
import time
from collections import defaultdict

print("=" * 80)
print("DIAGNÓSTICO DE PERFORMANCE - RECORDPAP")
print("=" * 80)

# 1. Habilitar logging de SQL
settings.DEBUG = True

# 2. Testar query simples
print("\n[TEST 1] Query simples sem relacionamentos")
print("-" * 80)
reset_queries()
start = time.time()
vendas = Venda.objects.filter(ativo=True)[:5]
for v in vendas:
    pass
elapsed = time.time() - start
print(f"Tempo: {elapsed:.3f}s")
print(f"Queries executadas: {len(connection.queries)}")
for i, q in enumerate(connection.queries[:5], 1):
    print(f"\n{i}. {q['sql'][:100]}...")
    print(f"   Tempo: {float(q['time']):.3f}s")

# 3. Testar listagem completa (problema)
print("\n\n[TEST 2] Listagem completa (problema actual)")
print("-" * 80)
reset_queries()
start = time.time()

factory = APIRequestFactory()
request = factory.get('/api/crm/vendas/?view=geral&data_inicio=2025-12-01&data_fim=2025-12-31')
request.user = Usuario.objects.filter(is_staff=True).first() or Usuario.objects.first()

view = VendaViewSet.as_view({'get': 'list'})
try:
    response = view(request)
    elapsed = time.time() - start
    print(f"Tempo total: {elapsed:.3f}s")
    print(f"Status: {response.status_code}")
except Exception as e:
    print(f"❌ Erro: {e}")
    elapsed = time.time() - start
    print(f"Tempo até erro: {elapsed:.3f}s")

print(f"\n📊 Total de queries: {len(connection.queries)}")

# Agrupar por tipo
query_types = defaultdict(int)
for q in connection.queries:
    sql = q['sql'].split()[0]
    query_types[sql] += 1

print("\nQueries por tipo:")
for sql_type, count in sorted(query_types.items(), key=lambda x: -x[1]):
    print(f"  {sql_type}: {count}")

# Encontrar queries mais lentas
print("\n⏱️  Top 10 queries mais lentas:")
sorted_queries = sorted(connection.queries, key=lambda x: -float(x['time']))
for i, q in enumerate(sorted_queries[:10], 1):
    time_ms = float(q['time']) * 1000
    sql_short = q['sql'][:80].replace('\n', ' ')
    print(f"{i}. {time_ms:.2f}ms - {sql_short}...")

# 4. Testar query com select_related
print("\n\n[TEST 3] Query com select_related (otimizado)")
print("-" * 80)
reset_queries()
start = time.time()
vendas = Venda.objects.filter(ativo=True).select_related(
    'vendedor', 'cliente', 'status_tratamento', 'status_esteira'
)[:10]
for v in vendas:
    _ = v.vendedor.nome
    _ = v.status_tratamento.nome
elapsed = time.time() - start
print(f"Tempo: {elapsed:.3f}s")
print(f"Queries: {len(connection.queries)}")

# 5. Analisar serializer
print("\n\n[TEST 4] VendaSerializer com many=True")
print("-" * 80)
reset_queries()
start = time.time()
queryset = Venda.objects.filter(ativo=True)[:20]
serializer = VendaSerializer(queryset, many=True)
data = serializer.data
elapsed = time.time() - start
print(f"Tempo: {elapsed:.3f}s")
print(f"Queries: {len(connection.queries)}")
print(f"Registros serializados: {len(data)}")

# Mostrar queries problemáticas
print("\nQueries lentas (>10ms):")
slow_queries = [q for q in connection.queries if float(q['time']) > 0.01]
for q in slow_queries[:5]:
    print(f"  {float(q['time'])*1000:.2f}ms - {q['sql'][:100]}...")

print("\n" + "=" * 80)
print("RECOMENDAÇÕES")
print("=" * 80)

total_queries = len(connection.queries)
if total_queries > 50:
    print(f"⚠️  Muitas queries ({total_queries}) - Procure por N+1 problems")
    print("   - Use select_related() para ForeignKeys")
    print("   - Use prefetch_related() para reverse ForeignKeys")
    print("   - Use only() ou defer() para campos específicos")
else:
    print(f"✅ Número de queries é aceitável ({total_queries})")

# Verificar índices
print("\n📋 Índices criados na tabela crm_venda:")
from django.db import connection
cursor = connection.cursor()
cursor.execute("""
    SELECT indexname FROM pg_indexes 
    WHERE tablename = 'crm_venda' 
    ORDER BY indexname;
""")
indexes = cursor.fetchall()
if indexes:
    for idx in indexes:
        print(f"  ✅ {idx[0]}")
else:
    print("  ❌ Nenhum índice encontrado!")

print("\n" + "=" * 80)
