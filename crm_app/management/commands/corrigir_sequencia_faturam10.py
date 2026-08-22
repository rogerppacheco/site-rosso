"""
Comando Django para corrigir a sequência da tabela FaturaM10 no PostgreSQL.

Este comando resolve o erro:
"duplicate key value violates unique constraint crm_app_faturam10_pkey"

Uso:
    python manage.py corrigir_sequencia_faturam10
"""
from django.core.management.base import BaseCommand
from django.db import connection
from crm_app.models import FaturaM10


class Command(BaseCommand):
    help = 'Corrige a sequência da tabela FaturaM10 no PostgreSQL para evitar erros de chave duplicada'

    def handle(self, *args, **options):
        self.stdout.write('Corrigindo sequencia da tabela FaturaM10...')
        
        try:
            # Obter o maior ID atual na tabela
            from django.db.models import Max
            max_id = FaturaM10.objects.aggregate(max_id=Max('id'))['max_id'] or 0
            
            self.stdout.write(f'   Maior ID encontrado: {max_id}')
            
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
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Sequencia corrigida! Proximo ID sera: {next_val + 1}'
                    )
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Erro ao corrigir sequencia: {str(e)}')
            )
            import traceback
            traceback.print_exc()
