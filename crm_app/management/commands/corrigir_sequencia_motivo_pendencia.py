"""
Comando Django para corrigir a sequência do PostgreSQL para a tabela crm_motivo_pendencia
Uso: python manage.py corrigir_sequencia_motivo_pendencia
"""
from django.core.management.base import BaseCommand
from django.db import connection
from crm_app.models import MotivoPendencia


class Command(BaseCommand):
    help = 'Corrige a sequência do PostgreSQL para a tabela crm_motivo_pendencia'

    def handle(self, *args, **options):
        table_name = MotivoPendencia._meta.db_table
        self.stdout.write(f"Tabela: {table_name}")
        
        with connection.cursor() as cursor:
            # Buscar o máximo ID atual
            cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_name};")
            max_id = cursor.fetchone()[0]
            
            self.stdout.write(f"   Máximo ID atual na tabela: {max_id}")
            
            # Obter o nome da sequência
            cursor.execute(f"SELECT pg_get_serial_sequence('{table_name}', 'id');")
            seq_name = cursor.fetchone()[0]
            
            if seq_name:
                # Atualizar a sequência para o próximo valor disponível
                cursor.execute(f"SELECT setval(%s, %s, true);", [seq_name, max_id])
                next_id = max_id + 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Sequência {seq_name} corrigida. Próximo ID será: {next_id}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ Sequência não encontrada para {table_name}"
                    )
                )
