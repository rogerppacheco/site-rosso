import os
import django
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

print("="*60)
print("📦 BACKUP FRACIONADO COM UTF-8 FORÇADO")
print("="*60)

def backup_app(apps_list, filename):
    print(f"\n🚀 Baixando: {', '.join(apps_list)} -> {filename}...")
    try:
        # A MUDANÇA ESTÁ AQUI: Abrimos o arquivo com encoding='utf-8'
        # e passamos o objeto de arquivo para o stdout do call_command
        with open(filename, 'w', encoding='utf-8') as f:
            call_command('dumpdata', *apps_list, stdout=f, indent=2)
        print("✅ Sucesso!")
        return True
    except Exception as e:
        print(f"❌ Falha ao baixar {filename}: {e}")
        return False

# Lote 1: A Base (Já temos, mas mal não faz baixar de novo)
apps_base = ['usuarios', 'auth', 'contenttypes', 'admin', 'sessions']
backup_app(apps_base, 'backup_parte1_users.json')

# Lote 2: Apps Satélites
apps_satelite = ['osab', 'presenca', 'relatorios', 'core']
backup_app(apps_satelite, 'backup_parte2_outros.json')

# Lote 3: O CRM (Onde costuma ter emojis e acentos)
apps_crm = ['crm_app']
backup_app(apps_crm, 'backup_parte3_crm.json')

print("\n🏁 Processo Finalizado.")
