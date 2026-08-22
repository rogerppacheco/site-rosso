#!/usr/bin/env python
"""
Script para verificar e corrigir a sequência do PostgreSQL para a tabela presenca
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

def verificar_e_corrigir_sequencia():
    table_name = Presenca._meta.db_table
    print(f"Tabela: {table_name}")
    
    with connection.cursor() as cursor:
        # Buscar o máximo ID atual
        cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_name};")
        max_id = cursor.fetchone()[0]
        print(f"MAX ID na tabela: {max_id}")
        
        # Buscar todas as sequências relacionadas
        cursor.execute("""
            SELECT sequence_name 
            FROM information_schema.sequences 
            WHERE sequence_name LIKE '%presenca%' OR sequence_name LIKE '%registros%'
            ORDER BY sequence_name;
        """)
        sequences = cursor.fetchall()
        print(f"\nSequencias encontradas:")
        for seq in sequences:
            seq_name = seq[0]
            cursor.execute(f"SELECT last_value, is_called FROM {seq_name};")
            result = cursor.fetchone()
            print(f"  {seq_name}: last_value={result[0]}, is_called={result[1]}")
        
        # Obter o nome da sequência usada pela tabela
        cursor.execute(f"SELECT pg_get_serial_sequence('{table_name}', 'id');")
        seq_result = cursor.fetchone()
        seq_name = seq_result[0] if seq_result[0] else None
        
        if seq_name:
            print(f"\nSequencia usada pela tabela: {seq_name}")
            cursor.execute(f"SELECT last_value, is_called FROM {seq_name};")
            result = cursor.fetchone()
            last_value = result[0]
            is_called = result[1]
            print(f"  last_value={last_value}, is_called={is_called}")
            
            # Calcular o próximo valor que seria usado
            if is_called:
                next_value = last_value + 1
            else:
                next_value = last_value
            
            print(f"\nProximo ID que seria usado: {next_value}")
            print(f"MAX ID atual na tabela: {max_id}")
            
            if next_value <= max_id:
                print(f"\nCORRIGINDO: Sequencia desatualizada!")
                # Corrigir para o próximo valor disponível (max_id + 1)
                cursor.execute(f"SELECT setval(%s, %s, true);", [seq_name, max_id])
                print(f"Sequencia corrigida. Proximo ID sera: {max_id + 1}")
            else:
                print(f"\nOK: Sequencia esta correta.")
        else:
            print("\nAVISO: Nenhuma sequencia encontrada para a tabela!")

if __name__ == '__main__':
    verificar_e_corrigir_sequencia()
