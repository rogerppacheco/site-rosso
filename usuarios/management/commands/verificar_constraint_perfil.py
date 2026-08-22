from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Verifica e corrige a constraint de foreign key do campo perfil'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Verificar constraints de foreign key na tabela usuarios_usuario
            cursor.execute("""
                SELECT
                    tc.constraint_name,
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = 'usuarios_usuario'
                    AND kcu.column_name = 'perfil_id';
            """)
            
            constraints = cursor.fetchall()
            
            self.stdout.write("=" * 80)
            self.stdout.write("CONSTRAINTS DE FOREIGN KEY PARA perfil_id:")
            self.stdout.write("=" * 80)
            
            for constraint in constraints:
                constraint_name, table_name, column_name, foreign_table, foreign_column = constraint
                self.stdout.write(f"\nConstraint: {constraint_name}")
                self.stdout.write(f"  Tabela: {table_name}")
                self.stdout.write(f"  Coluna: {column_name}")
                self.stdout.write(f"  Tabela Referenciada: {foreign_table}")
                self.stdout.write(f"  Coluna Referenciada: {foreign_column}")
                
                if foreign_table == 'tpl_usuarios_perfil':
                    self.stdout.write(self.style.ERROR(f"\n  ⚠️ PROBLEMA: Constraint aponta para {foreign_table} (tabela de outro projeto)"))
                    self.stdout.write(self.style.WARNING(f"  ⚠️ Deveria apontar para: usuarios_perfil"))
                elif foreign_table == 'usuarios_perfil':
                    self.stdout.write(self.style.SUCCESS(f"\n  ✅ OK: Constraint aponta corretamente para {foreign_table}"))
            
            self.stdout.write("\n" + "=" * 80)
