#!/usr/bin/env python
"""
Script para corrigir a sequência do PostgreSQL para a tabela registros_presenca
"""
import os
import sys
import django

# Configurar Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import connection
from presenca.models import Presenca

def corrigir_sequencia():
    table_name = Presenca._meta.db_table
    print(f"Tabela: {table_name}")
    
    with connection.cursor() as cursor:
        # Buscar o máximo ID atual
        cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_name};")
        max_id = cursor.fetchone()[0]
        
        # Obter o nome da sequência
        cursor.execute(f"SELECT pg_get_serial_sequence('{table_name}', 'id');")
        seq_name = cursor.fetchone()[0]
        
        if seq_name:
            # Atualizar a sequência para o próximo valor disponível
            cursor.execute(f"SELECT setval(%s, %s, false);", [seq_name, max_id])
            print(f"OK - Sequencia {seq_name} corrigida. Proximo ID sera: {max_id + 1}")
            print(f"   Maximo ID atual na tabela: {max_id}")
        else:
            print(f"⚠️ Sequência não encontrada para {table_name}")

if __name__ == '__main__':
    corrigir_sequencia()
