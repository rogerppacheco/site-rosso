"""
Verificar formato dos números de ordem no banco
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10

print("\n" + "=" * 100)
print("🔍 VERIFICAÇÃO DE FORMATO DE NÚMEROS DE ORDEM")
print("=" * 100)

# 1. Verificar ImportacaoFPD
print("\n1️⃣ ImportacaoFPD - Como estão salvos:")
fpd_sample = ImportacaoFPD.objects.all()[:20]
print(f"   Amostra de {len(fpd_sample)} registros:\n")

for imp in fpd_sample:
    nr_ordem = imp.nr_ordem
    print(f"   {nr_ordem:15s} | Tipo: {type(nr_ordem).__name__:10s} | Len: {len(nr_ordem):2d} | Fatura: {imp.nr_fatura}")

# 2. Verificar ContratoM10
print("\n2️⃣ ContratoM10 - Como estão salvos:")
m10_sample = ContratoM10.objects.all()[:10]
print(f"   Amostra de {len(m10_sample)} registros:\n")

for contrato in m10_sample:
    os = contrato.ordem_servico
    print(f"   {os:15s} | Tipo: {type(os).__name__:10s} | Len: {len(os):2d} | Cliente: {contrato.cliente_nome[:30]}")

# 3. Testar busca
print("\n3️⃣ Testando buscas:")
teste_os = "7086739"
print(f"\n   Procurando por: '{teste_os}'")

# Busca exata
fpd_exato = ImportacaoFPD.objects.filter(nr_ordem=teste_os).first()
if fpd_exato:
    print(f"   ✅ Encontrado em ImportacaoFPD (busca exata)")
    print(f"      nr_ordem no banco: '{fpd_exato.nr_ordem}'")
else:
    print(f"   ❌ NÃO encontrado em ImportacaoFPD (busca exata)")

# Busca com zero
teste_os_zero = f"0{teste_os}"
fpd_zero = ImportacaoFPD.objects.filter(nr_ordem=teste_os_zero).first()
if fpd_zero:
    print(f"   ✅ Encontrado com zero: '{fpd_zero.nr_ordem}'")
else:
    print(f"   ❌ NÃO encontrado com zero")

# Busca contains
fpd_contains = ImportacaoFPD.objects.filter(nr_ordem__contains=teste_os).first()
if fpd_contains:
    print(f"   ✅ Encontrado com contains: '{fpd_contains.nr_ordem}'")
else:
    print(f"   ❌ NÃO encontrado com contains")

# 4. Verificar duplicatas e formatos
print("\n4️⃣ Análise de formatos:")
from django.db.models import Count

# Contar por tamanho de nr_ordem
print("\n   Distribuição por tamanho de nr_ordem:")
from django.db.models.functions import Length
from django.db.models import Count

# Como Length pode não funcionar com SQLite, vamos fazer manual
tamanhos = {}
for imp in ImportacaoFPD.objects.all():
    tam = len(imp.nr_ordem)
    tamanhos[tam] = tamanhos.get(tam, 0) + 1

for tam, qtd in sorted(tamanhos.items()):
    print(f"   Tamanho {tam}: {qtd} registros")

# Verificar se tem zeros à esquerda
print("\n   Verificando zeros à esquerda:")
com_zero = 0
sem_zero = 0
for imp in ImportacaoFPD.objects.all()[:100]:
    if imp.nr_ordem.startswith('0'):
        com_zero += 1
    else:
        sem_zero += 1

print(f"   Com zero à esquerda: {com_zero}")
print(f"   Sem zero à esquerda: {sem_zero}")

# 5. Exemplos específicos
print("\n5️⃣ Exemplos de O.S que existem no ImportacaoFPD:")
exemplos = ImportacaoFPD.objects.values_list('nr_ordem', flat=True).distinct()[:10]
print("   " + ", ".join(exemplos))

print("\n6️⃣ Exemplos de O.S que existem no ContratoM10:")
exemplos_m10 = ContratoM10.objects.values_list('ordem_servico', flat=True)[:10]
print("   " + ", ".join(exemplos_m10))

print("\n" + "=" * 100)
print("💡 RECOMENDAÇÕES:")
print("=" * 100)
print("\n   Para buscar uma O.S no ImportacaoFPD, use:")
print("   - Formato exato como está no banco (sem zeros extras)")
print("   - Ou use busca parcial: ImportacaoFPD.objects.filter(nr_ordem__contains='7086739')")
print("\n" + "=" * 100)
