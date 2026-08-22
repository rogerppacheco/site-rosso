"""
Script para verificar duplicatas de nr_ordem_venda na tabela ImportacaoAgendamento
"""
import os
import sys
from pathlib import Path

# Garantir que o diretório do projeto esteja no sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from crm_app.models import ImportacaoAgendamento
from django.db.models import Count

print("\n" + "=" * 80)
print("🔍 VERIFICAÇÃO DE DUPLICATAS - ImportacaoAgendamento")
print("=" * 80)

# Estatísticas gerais
total_registros = ImportacaoAgendamento.objects.count()
total_com_nr_ordem_venda = ImportacaoAgendamento.objects.exclude(nr_ordem_venda__isnull=True).exclude(nr_ordem_venda='').count()
total_unicos = ImportacaoAgendamento.objects.exclude(nr_ordem_venda__isnull=True).exclude(nr_ordem_venda='').values('nr_ordem_venda').distinct().count()

print(f"\n📊 ESTATÍSTICAS GERAIS:")
print(f"   Total de registros: {total_registros}")
print(f"   Registros com nr_ordem_venda preenchido: {total_com_nr_ordem_venda}")
print(f"   Total de nr_ordem_venda únicos: {total_unicos}")

# Verificar duplicatas
duplicados = ImportacaoAgendamento.objects.values('nr_ordem_venda').annotate(
    count=Count('id')
).filter(
    count__gt=1,
    nr_ordem_venda__isnull=False
).exclude(
    nr_ordem_venda=''
).order_by('-count')

total_duplicados = duplicados.count()
registros_duplicados = sum(d['count'] for d in duplicados)

print(f"\n🔴 DUPLICATAS:")
print(f"   Total de nr_ordem_venda com duplicatas: {total_duplicados}")
print(f"   Total de registros envolvidos em duplicatas: {registros_duplicados}")

if total_duplicados > 0:
    print(f"\n   Top 20 nr_ordem_venda mais duplicados:")
    for idx, dup in enumerate(duplicados[:20], 1):
        nr = dup['nr_ordem_venda']
        count = dup['count']
        print(f"   {idx:2d}. nr_ordem_venda: [{nr}] - {count} registros")
        
        # Mostrar IDs dos registros duplicados
        regs = ImportacaoAgendamento.objects.filter(nr_ordem_venda=nr).values_list('id', 'dt_inicio_agendamento', 'cd_nrba')[:5]
        for reg_id, dt, cd_nrba in regs:
            dt_str = dt.strftime('%d/%m/%Y %H:%M') if dt else 'Sem data'
            print(f"       - ID: {reg_id}, dt_inicio: {dt_str}, cd_nrba: {cd_nrba}")
else:
    print("\n   ✅ Nenhuma duplicata encontrada!")

print("\n" + "=" * 80)
