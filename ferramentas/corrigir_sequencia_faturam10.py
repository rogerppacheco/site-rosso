"""
Script para corrigir a sequência da tabela FaturaM10 no PostgreSQL.

Este script resolve o erro:
"duplicate key value violates unique constraint crm_app_faturam10_pkey"

Uso:
    python ferramentas/corrigir_sequencia_faturam10.py
"""
import os
import sys
import django

# Configurar Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'site_record.settings')
django.setup()

from django.db import connection
from crm_app.models import FaturaM10
from django.db.models import Max


def corrigir_sequencia():
    """Corrige a sequência da tabela FaturaM10"""
    print('🔧 Corrigindo sequência da tabela FaturaM10...')
    
    try:
        # Obter o maior ID atual na tabela
        max_id = FaturaM10.objects.aggregate(max_id=Max('id'))['max_id'] or 0
        
        print(f'   Maior ID encontrado: {max_id}')
        
        # Corrigir a sequência usando o nome correto da tabela no PostgreSQL
        with connection.cursor() as cursor:
            # O nome da tabela no PostgreSQL é crm_app_faturam10
            cursor.execute("""
                SELECT setval(
                    pg_get_serial_sequence('crm_app_faturam10', 'id'),
                    COALESCE((SELECT MAX(id) FROM crm_app_faturam10), 1),
                    true
                );
            """)
            
            # Verificar o próximo valor da sequência
            cursor.execute("""
                SELECT currval(pg_get_serial_sequence('crm_app_faturam10', 'id'));
            """)
            next_val = cursor.fetchone()[0]
            
            print(f'✅ Sequência corrigida! Próximo ID será: {next_val + 1}')
            print('\n💡 Agora você pode tentar fazer o upload do FPD novamente.')
            
    except Exception as e:
        print(f'❌ Erro ao corrigir sequência: {str(e)}')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    corrigir_sequencia()
