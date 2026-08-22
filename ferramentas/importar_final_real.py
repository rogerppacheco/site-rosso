import os
import django
from django.core.management import call_command
from django.db import transaction, connection
from django.db.models import signals
from django.core import serializers

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

print("="*60)
print("🚀 IMPORTAÇÃO MESTRA (CORREÇÃO CONTENT_TYPES)")
print("="*60)

def lobotomizar_signals():
    print("🔇 Neutralizando signals...")
    def no_op(sender, **kwargs): return []
    signals.pre_save.send = no_op
    signals.post_save.send = no_op
    signals.m2m_changed.send = no_op
    signals.pre_delete.send = no_op
    signals.post_delete.send = no_op

def limpar_tabelas_conflitantes():
    """
    Remove dados recriados automaticamente pelo Django após o flush
    para permitir a importação dos IDs originais do backup.
    """
    print("\n🧹 Limpando tabela django_content_type para evitar conflitos...")
    with connection.cursor() as cursor:
        # TRUNCATE CASCADE apaga os content_types e as permissions associadas
        # Isso é seguro pois vamos importar tudo do backup logo em seguida
        cursor.execute("TRUNCATE TABLE django_content_type CASCADE;")
    print("✅ Tabela limpa. Pronto para receber backup.")

def importar_simples(arquivo, nome_fase):
    print(f"\n📥 [{nome_fase}] Importando {arquivo}...")
    if not os.path.exists(arquivo):
        print(f"❌ Arquivo não encontrado: {arquivo}")
        return False
    try:
        call_command('loaddata', arquivo)
        print("✅ Sucesso!")
        return True
    except Exception as e:
        print(f"❌ Erro na fase {nome_fase}: {e}")
        return False

def importar_em_lotes(arquivo, nome_fase):
    print(f"\n📥 [{nome_fase}] Importando {arquivo} EM LOTES...")
    if not os.path.exists(arquivo):
        print("❌ Arquivo não encontrado.")
        return
    
    with open(arquivo, 'r', encoding='utf-8') as f:
        objects = serializers.deserialize("json", f.read())
        batch = []
        batch_size = 1000
        
        for i, obj in enumerate(objects, 1):
            batch.append(obj)
            if len(batch) >= batch_size:
                salvar_lote(batch)
                batch = []
                print(f"   Processados: {i}...", end='\r')
        
        if batch:
            salvar_lote(batch)
            
        print(f"\n✅ [{nome_fase}] Concluído!")

def salvar_lote(object_list):
    try:
        with transaction.atomic():
            for obj in object_list:
                obj.save()
    except Exception as e:
        print(f"\n❌ Erro ao salvar lote: {e}")

def fix_sequences():
    print("\n🔢 Ajustando sequências...")
    meus_apps = ['crm_app', 'usuarios', 'financeiro', 'auth', 'contenttypes', 'admin', 'sessions', 'core', 'osab']
    from io import StringIO
    output = StringIO()
    try:
        call_command('sqlsequencereset', *meus_apps, stdout=output)
        with connection.cursor() as cursor:
            cursor.execute(output.getvalue())
        print("✅ Sequências corrigidas.")
    except Exception:
        pass

if __name__ == "__main__":
    lobotomizar_signals()
    
    # IMPORTANTE: Limpa conflitos antes da Fase 1
    limpar_tabelas_conflitantes()
    
    if importar_simples('backup_parte1_users.json', 'FASE 1 (BASE)'):
        importar_simples('backup_parte2_outros.json', 'FASE 2 (SATÉLITES)')
        importar_em_lotes('backup_parte3_crm.json', 'FASE 3 (CRM)')
        fix_sequences()
    else:
        print("⛔ Falha crítica na Fase 1.")

def lobotomizar_signals():
    print("🔇 Neutralizando signals...")
    def no_op(sender, **kwargs): return []
    signals.pre_save.send = no_op
    signals.post_save.send = no_op
    signals.m2m_changed.send = no_op
    signals.pre_delete.send = no_op
    signals.post_delete.send = no_op

def limpar_tabelas_conflitantes():
    """
    Remove dados recriados automaticamente pelo Django após o flush
    para permitir a importação dos IDs originais do backup.
    """
    print("\n🧹 Limpando tabela django_content_type para evitar conflitos...")
    with connection.cursor() as cursor:
        # TRUNCATE CASCADE apaga os content_types e as permissions associadas
        # Isso é seguro pois vamos importar tudo do backup logo em seguida
        cursor.execute("TRUNCATE TABLE django_content_type CASCADE;")
    print("✅ Tabela limpa. Pronto para receber backup.")

def importar_simples(arquivo, nome_fase):
    print(f"\n📥 [{nome_fase}] Importando {arquivo}...")
    if not os.path.exists(arquivo):
        print(f"❌ Arquivo não encontrado: {arquivo}")
        return False
    try:
        call_command('loaddata', arquivo)
        print("✅ Sucesso!")
        return True
    except Exception as e:
        print(f"❌ Erro na fase {nome_fase}: {e}")
        return False

def importar_em_lotes(arquivo, nome_fase):
    print(f"\n📥 [{nome_fase}] Importando {arquivo} EM LOTES...")
    if not os.path.exists(arquivo):
        print("❌ Arquivo não encontrado.")
        return
    
    with open(arquivo, 'r', encoding='utf-8') as f:
        objects = serializers.deserialize("json", f.read())
        batch = []
        batch_size = 1000
        
        for i, obj in enumerate(objects, 1):
            batch.append(obj)
            if len(batch) >= batch_size:
                salvar_lote(batch)
                batch = []
                print(f"   Processados: {i}...", end='\r')
        
        if batch:
            salvar_lote(batch)
            
        print(f"\n✅ [{nome_fase}] Concluído!")

def salvar_lote(object_list):
    try:
        with transaction.atomic():
            for obj in object_list:
                obj.save()
    except Exception as e:
        print(f"\n❌ Erro ao salvar lote: {e}")

def fix_sequences():
    print("\n🔢 Ajustando sequências...")
    meus_apps = ['crm_app', 'usuarios', 'financeiro', 'auth', 'contenttypes', 'admin', 'sessions', 'core', 'osab']
    from io import StringIO
    output = StringIO()
    try:
        call_command('sqlsequencereset', *meus_apps, stdout=output)
        with connection.cursor() as cursor:
            cursor.execute(output.getvalue())
        print("✅ Sequências corrigidas.")
    except Exception:
        pass

if __name__ == "__main__":
    lobotomizar_signals()
    
    # IMPORTANTE: Limpa conflitos antes da Fase 1
    limpar_tabelas_conflitantes()
    
    if importar_simples('backup_parte1_users.json', 'FASE 1 (BASE)'):
        importar_simples('backup_parte2_outros.json', 'FASE 2 (SATÉLITES)')
        importar_em_lotes('backup_parte3_crm.json', 'FASE 3 (CRM)')
        fix_sequences()
    else:
        print("⛔ Falha crítica na Fase 1.")
