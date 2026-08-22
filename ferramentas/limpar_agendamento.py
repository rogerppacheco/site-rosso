"""
Script para limpar todos os registros da tabela ImportacaoAgendamento
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

print("\n" + "=" * 80)
print("🗑️  LIMPEZA DE DADOS - ImportacaoAgendamento")
print("=" * 80)

# Contar registros antes da limpeza
total_antes = ImportacaoAgendamento.objects.count()
print(f"\n📊 Total de registros ANTES da limpeza: {total_antes}")

if total_antes == 0:
    print("\n   ✅ A tabela já está vazia!")
    print("\n" + "=" * 80)
    sys.exit(0)

# Confirmar ação
print(f"\n⚠️  ATENÇÃO: Esta operação irá deletar TODOS os {total_antes} registros!")
print("   Esta ação NÃO PODE ser desfeita!")
resposta = input("\n   Deseja continuar? (digite 'SIM' para confirmar): ")

if resposta != 'SIM':
    print("\n   ❌ Operação cancelada pelo usuário.")
    print("\n" + "=" * 80)
    sys.exit(0)

# Deletar todos os registros
print("\n🔄 Deletando registros...")
deletados, _ = ImportacaoAgendamento.objects.all().delete()

# Verificar resultado
total_depois = ImportacaoAgendamento.objects.count()

print(f"\n✅ LIMPEZA CONCLUÍDA:")
print(f"   Registros deletados: {deletados}")
print(f"   Total de registros DEPOIS da limpeza: {total_depois}")

if total_depois == 0:
    print("\n   ✅ Tabela limpa com sucesso!")
else:
    print(f"\n   ⚠️  Ainda restam {total_depois} registros na tabela.")

print("\n" + "=" * 80)
