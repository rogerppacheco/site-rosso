"""
Comando para criar permissões faltantes em produção
Usa create_permissions do Django para criar todas as permissões dos apps especificados
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.management import create_permissions
from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

class Command(BaseCommand):
    help = 'Cria permissões faltantes para os apps especificados'

    def handle(self, *args, **options):
        meus_apps = ['crm_app', 'usuarios', 'presenca', 'osab', 'relatorios']
        
        self.stdout.write("=" * 60)
        self.stdout.write("CRIANDO PERMISSÕES FALTANTES")
        self.stdout.write("=" * 60)
        
        total_criadas = 0
        
        for app_label in meus_apps:
            try:
                app_config = apps.get_app_config(app_label)
                self.stdout.write(f"\n{app_label.upper()}:")
                
                # Verificar quantas permissões existem antes
                antes = Permission.objects.filter(content_type__app_label=app_label).count()
                self.stdout.write(f"  Permissões antes: {antes}")
                
                # Criar permissões para este app
                # Isso usa o mesmo mecanismo que o Django usa em post_migrate
                create_permissions(app_config, verbosity=0)
                
                # Verificar quantas permissões existem depois
                depois = Permission.objects.filter(content_type__app_label=app_label).count()
                criadas = depois - antes
                
                self.stdout.write(f"  Permissões depois: {depois}")
                
                if criadas > 0:
                    self.stdout.write(self.style.SUCCESS(f"  OK: Criadas {criadas} permissoes"))
                    total_criadas += criadas
                else:
                    self.stdout.write(self.style.WARNING(f"  ATENCAO: Nenhuma permissao nova criada (ja existiam {antes})"))
                    
            except LookupError:
                self.stdout.write(self.style.ERROR(f"  ERRO: App '{app_label}' nao encontrado"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ERRO: Erro ao criar permissoes: {e}"))
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"Total de permissões criadas: {total_criadas}"))
        self.stdout.write("=" * 60)
        
        # Mostrar resumo final
        self.stdout.write("\nRESUMO FINAL:")
        for app_label in meus_apps:
            count = Permission.objects.filter(content_type__app_label=app_label).count()
            self.stdout.write(f"  {app_label}: {count} permissões")
