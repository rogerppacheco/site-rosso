"""
Script para verificar logs de importação que estão travados (status PROCESSANDO há muito tempo)
"""
import os
import sys
from pathlib import Path
from datetime import timedelta

# Garantir que o diretório do projeto esteja no sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from crm_app.models import LogImportacaoFPD, LogImportacaoAgendamento
from django.utils import timezone

print("\n" + "=" * 80)
print("🔍 VERIFICAÇÃO DE LOGS TRAVADOS")
print("=" * 80)

# Verificar LogImportacaoFPD
logs_fpd_travados = LogImportacaoFPD.objects.filter(status='PROCESSANDO').order_by('-iniciado_em')
print(f"\n📊 LOGS FPD PROCESSANDO: {logs_fpd_travados.count()}")

for log in logs_fpd_travados[:10]:
    if log.iniciado_em:
        tempo_decorrido = timezone.now() - log.iniciado_em
        tempo_segundos = tempo_decorrido.total_seconds()
        tempo_minutos = tempo_segundos / 60
        
        print(f"\n   ID: {log.id}")
        print(f"   Arquivo: {log.nome_arquivo}")
        print(f"   Iniciado: {log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"   Tempo decorrido: {tempo_minutos:.1f} minutos ({tempo_segundos:.0f} segundos)")
        print(f"   Usuário: {log.usuario.username if log.usuario else 'N/A'}")
        print(f"   Total linhas: {log.total_linhas or 0}")
        
        if tempo_minutos > 30:
            print(f"   ⚠️  TRAVADO há mais de 30 minutos!")

# Verificar LogImportacaoAgendamento
logs_agend_travados = LogImportacaoAgendamento.objects.filter(status='PROCESSANDO').order_by('-iniciado_em')
print(f"\n📊 LOGS AGENDAMENTO PROCESSANDO: {logs_agend_travados.count()}")

for log in logs_agend_travados[:10]:
    if log.iniciado_em:
        tempo_decorrido = timezone.now() - log.iniciado_em
        tempo_segundos = tempo_decorrido.total_seconds()
        tempo_minutos = tempo_segundos / 60
        
        print(f"\n   ID: {log.id}")
        print(f"   Arquivo: {log.nome_arquivo}")
        print(f"   Iniciado: {log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"   Tempo decorrido: {tempo_minutos:.1f} minutos ({tempo_segundos:.0f} segundos)")
        print(f"   Usuário: {log.usuario.username if log.usuario else 'N/A'}")
        print(f"   Total linhas: {log.total_linhas or 0}")
        
        if tempo_minutos > 30:
            print(f"   ⚠️  TRAVADO há mais de 30 minutos!")

print("\n" + "=" * 80)
print("💡 DICA: Se um processo está travado há muito tempo, pode ser:")
print("   1. Thread foi interrompida")
print("   2. Erro não capturado no código")
print("   3. Processo muito lento para grandes arquivos")
print("   4. Problema de conexão com banco de dados")
print("\n" + "=" * 80)
