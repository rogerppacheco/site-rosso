#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ImportacaoFPD, LogImportacaoFPD

# Limpar dados antigos
print("🗑️  Limpando dados antigos...")
print(f"   ImportacaoFPD: {ImportacaoFPD.objects.count()} registros")
print(f"   LogImportacaoFPD: {LogImportacaoFPD.objects.count()} logs")

# Deletar tudo
ImportacaoFPD.objects.all().delete()
LogImportacaoFPD.objects.all().delete()

print(f"\n✅ Limpeza completa")
print(f"   ImportacaoFPD: {ImportacaoFPD.objects.count()} registros")
print(f"   LogImportacaoFPD: {LogImportacaoFPD.objects.count()} logs")
