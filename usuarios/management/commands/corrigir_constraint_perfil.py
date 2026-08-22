from django.core.management.base import BaseCommand
from django.db import connection, transaction

class Command(BaseCommand):
    help = 'Corrige a constraint de foreign key do campo perfil para apontar para usuarios_perfil'

    def handle(self, *args, **options):
        self.stdout.write("=" * 80)
        self.stdout.write("CORRIGINDO CONSTRAINT DE FOREIGN KEY")
        self.stdout.write("=" * 80)
        
        with connection.cursor() as cursor:
            try:
                # 1. Verificar constraints existentes
                cursor.execute("""
                    SELECT constraint_name
                    FROM information_schema.table_constraints
                    WHERE constraint_type = 'FOREIGN KEY'
                        AND table_name = 'usuarios_usuario'
                        AND constraint_name LIKE '%perfil%';
                """)
                
                constraints = cursor.fetchall()
                constraint_names = [c[0] for c in constraints]
                
                if not constraint_names:
                    self.stdout.write(self.style.WARNING("\n⚠️ Nenhuma constraint encontrada para perfil_id"))
                    return
                
                self.stdout.write(f"\nEncontradas {len(constraint_names)} constraint(s):")
                for name in constraint_names:
                    self.stdout.write(f"  - {name}")
                
                # 2. Verificar qual tabela a constraint atual aponta
                cursor.execute("""
                    SELECT
                        tc.constraint_name,
                        ccu.table_name AS foreign_table_name
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                        AND tc.table_name = 'usuarios_usuario'
                        AND tc.constraint_name = %s;
                """, [constraint_names[0]])
                
                result = cursor.fetchone()
                if result:
                    constraint_name, current_foreign_table = result
                    self.stdout.write(f"\nConstraint '{constraint_name}' atualmente aponta para: {current_foreign_table}")
                    
                    if current_foreign_table == 'usuarios_perfil':
                        self.stdout.write(self.style.SUCCESS("\n✅ Constraint já está correta! Nenhuma alteração necessária."))
                        return
                    
                    if current_foreign_table == 'tpl_usuarios_perfil':
                        self.stdout.write(self.style.WARNING(f"\n⚠️ Constraint aponta para tabela de outro projeto: {current_foreign_table}"))
                        self.stdout.write("Corrigindo...")
                        
                        with transaction.atomic():
                            # 3. Verificar se a tabela usuarios_perfil existe
                            cursor.execute("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables 
                                    WHERE table_schema = 'public' 
                                    AND table_name = 'usuarios_perfil'
                                );
                            """)
                            tabela_existe = cursor.fetchone()[0]
                            
                            if not tabela_existe:
                                self.stdout.write(self.style.ERROR("\n❌ ERRO: Tabela usuarios_perfil não existe!"))
                                self.stdout.write("Crie a tabela primeiro usando: python manage.py criar_tabela_perfil")
                                return
                            
                            # 4. Limpar perfil_id inválidos (que apontam para IDs que não existem em usuarios_perfil)
                            self.stdout.write("\n1. Limpando perfil_id inválidos...")
                            cursor.execute("""
                                UPDATE usuarios_usuario
                                SET perfil_id = NULL
                                WHERE perfil_id IS NOT NULL
                                AND perfil_id NOT IN (SELECT id FROM usuarios_perfil);
                            """)
                            rows_afetadas = cursor.rowcount
                            if rows_afetadas > 0:
                                self.stdout.write(self.style.WARNING(f"   {rows_afetadas} usuário(s) tiveram perfil_id limpo (apontavam para IDs inexistentes)"))
                            else:
                                self.stdout.write("   Nenhum perfil_id inválido encontrado")
                            
                            # 5. Dropar a constraint antiga
                            self.stdout.write(f"\n2. Removendo constraint '{constraint_name}'...")
                            cursor.execute(f"ALTER TABLE usuarios_usuario DROP CONSTRAINT IF EXISTS {constraint_name};")
                            
                            # 6. Criar a constraint correta
                            self.stdout.write("3. Criando constraint apontando para usuarios_perfil...")
                            new_constraint_name = 'usuarios_usuario_perfil_id_fk_usuarios_perfil'
                            cursor.execute(f"""
                                ALTER TABLE usuarios_usuario
                                ADD CONSTRAINT {new_constraint_name}
                                FOREIGN KEY (perfil_id)
                                REFERENCES usuarios_perfil(id)
                                ON DELETE SET NULL;
                            """)
                            
                            self.stdout.write(self.style.SUCCESS(f"\n✅ Constraint '{new_constraint_name}' criada com sucesso!"))
                            
                else:
                    self.stdout.write(self.style.WARNING("\n⚠️ Não foi possível determinar a tabela referenciada"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\n❌ ERRO: {e}"))
                transaction.rollback()
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("Processo concluído!"))
