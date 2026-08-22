"""
Limpar ImportacaoFPD e preparar para reimportar com zeros
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD

print("\n" + "=" * 100)
print("🗑️ LIMPANDO IMPORTACAOFPD")
print("=" * 100)

total_antes = ImportacaoFPD.objects.count()
print(f"\n📊 Registros antes: {total_antes}")

# Deletar todos
ImportacaoFPD.objects.all().delete()

total_depois = ImportacaoFPD.objects.count()
print(f"✅ Registros depois: {total_depois}")

print("\n" + "=" * 100)
print("🔄 PRONTO PARA REIMPORTAR COM ZEROS!")
print("=" * 100)
