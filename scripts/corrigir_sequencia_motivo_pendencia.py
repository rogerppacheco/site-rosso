#!/usr/bin/env python
"""
Script para corrigir a sequência do PostgreSQL para a tabela crm_motivo_pendencia
"""
import os
import sys
import django

# Configurar Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import connection
from crm_app.models import MotivoPendencia

def corrigir_sequencia():
    table_name = MotivoPendencia._meta.db_table
    print(f"Tabela: {table_name}")
    
    with connection.cursor() as cursor:
        # Buscar o máximo ID atual
        cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_name};")
        max_id = cursor.fetchone()[0]
        
        print(f"   Máximo ID atual na tabela: {max_id}")
        
        # Obter o nome da sequência
        cursor.execute(f"SELECT pg_get_serial_sequence('{table_name}', 'id');")
        seq_name = cursor.fetchone()[0]
        
        if seq_name:
            # Atualizar a sequência para o próximo valor disponível
            # Usando true para que o próximo valor seja max_id + 1
            cursor.execute(f"SELECT setval(%s, %s, true);", [seq_name, max_id])
            next_id = max_id + 1
            print(f"OK - Sequencia {seq_name} corrigida. Proximo ID sera: {next_id}")
        else:
            print(f"ERRO - Sequencia nao encontrada para {table_name}")

if __name__ == '__main__':
    corrigir_sequencia()
