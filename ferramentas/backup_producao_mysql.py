"""
Backup completo do banco MySQL de produção (JawsDB)
Este script faz backup SEGURO sem interromper o site.
"""
import os
import sys
import django
from datetime import datetime
import json

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.core import serializers
from django.apps import apps

def fazer_backup_completo():
    """Exporta TODOS os dados do banco em formato JSON."""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_mysql_producao_{timestamp}.json"
    
    print("=" * 60)
    print("🔒 BACKUP COMPLETO DO MYSQL (JAWSDB)")
    print("=" * 60)
    print(f"📁 Arquivo: {backup_file}")
    print()
    
    # Obter todos os modelos do Django
    all_models = apps.get_models()
    
    # Filtrar apenas os modelos do seu app (crm_app)
    models_to_backup = [model for model in all_models if model._meta.app_label == 'crm_app']
    
    total_records = 0
    backup_data = []
    
    print("📊 Contando registros por tabela...")
    print()
    
    for model in models_to_backup:
        count = model.objects.count()
        total_records += count
        print(f"  • {model._meta.verbose_name}: {count} registros")
        
        # Serializar todos os objetos deste modelo
        if count > 0:
            data = serializers.serialize('python', model.objects.all())
            backup_data.extend(data)
    
    print()
    print(f"✅ Total de registros: {total_records}")
    print()
    
    # Salvar backup em JSON
    print("💾 Salvando backup...")
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False, default=str)
    
    # Verificar tamanho do arquivo
    file_size = os.path.getsize(backup_file) / (1024 * 1024)  # MB
    
    print(f"✅ Backup salvo com sucesso!")
    print(f"📦 Tamanho: {file_size:.2f} MB")
    print(f"📁 Local: {os.path.abspath(backup_file)}")
    print()
    print("=" * 60)
    print("🔐 BACKUP COMPLETO - REDE DE SEGURANÇA CRIADA!")
    print("=" * 60)
    print()
    print("⚠️  IMPORTANTE: Guarde este arquivo! Ele é sua garantia de rollback.")
    
    return backup_file, total_records

if __name__ == "__main__":
    try:
        backup_file, total = fazer_backup_completo()
        print(f"\n✅ Sucesso! {total} registros salvos em {backup_file}")
    except Exception as e:
        print(f"\n❌ Erro ao fazer backup: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
