"""
Comando para corrigir a sequência de IDs das permissões
Ajusta a sequência do PostgreSQL para o próximo ID disponível
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth.models import Permission

class Command(BaseCommand):
    help = 'Corrige a sequencia de IDs das permissoes no PostgreSQL'

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("CORRIGINDO SEQUENCIA DE PERMISSOES")
        self.stdout.write("=" * 60)
        
        with connection.cursor() as cursor:
            # Obter o maior ID atual de permissões
            cursor.execute("SELECT MAX(id) FROM auth_permission;")
            max_id = cursor.fetchone()[0]
            
            if max_id is None:
                max_id = 1
            else:
                max_id = max_id + 1
            
            self.stdout.write(f"\nMaior ID encontrado: {max_id - 1}")
            self.stdout.write(f"Proximo ID sera: {max_id}")
            
            # Corrigir a sequência
            cursor.execute(f"SELECT setval('auth_permission_id_seq', {max_id}, false);")
            
            # Verificar o valor atual da sequência
            cursor.execute("SELECT last_value FROM auth_permission_id_seq;")
            current_seq = cursor.fetchone()[0]
            
            self.stdout.write(f"Sequencia corrigida para: {current_seq}")
            self.stdout.write(self.style.SUCCESS("\nOK: Sequencia corrigida com sucesso!"))
        
        # Mostrar resumo
        self.stdout.write("\n" + "=" * 60)
        total_perms = Permission.objects.all().count()
        self.stdout.write(f"Total de permissoes no banco: {total_perms}")
        self.stdout.write("=" * 60)
