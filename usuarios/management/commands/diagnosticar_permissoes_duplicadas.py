"""
Comando para diagnosticar permissões duplicadas
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

class Command(BaseCommand):
    help = 'Diagnostica permissões duplicadas no banco de dados'

    def handle(self, *args, **options):
        meus_apps = ['crm_app', 'usuarios', 'presenca', 'osab', 'relatorios']
        
        self.stdout.write("=" * 60)
        self.stdout.write("DIAGNÓSTICO DE PERMISSÕES DUPLICADAS")
        self.stdout.write("=" * 60)
        
        # Buscar permissões com mesmo codename e name, mas diferentes content_types
        perms = Permission.objects.filter(content_type__app_label__in=meus_apps).values('codename', 'name').annotate(count=Count('id')).filter(count__gt=1)
        
        if perms.exists():
            self.stdout.write(self.style.WARNING(f"\nEncontradas {perms.count()} permissões com codename/name duplicados:\n"))
            
            for perm in perms:
                codename = perm['codename']
                name = perm['name']
                count = perm['count']
                
                self.stdout.write(f"\n  Codename: {codename}")
                self.stdout.write(f"  Name: {name}")
                self.stdout.write(f"  Quantidade: {count}")
                
                # Mostrar os detalhes de cada permissão duplicada
                detalhes = Permission.objects.filter(codename=codename, name=name, content_type__app_label__in=meus_apps).select_related('content_type')
                
                for p in detalhes:
                    self.stdout.write(f"    - ID: {p.id}, App: {p.content_type.app_label}, Model: {p.content_type.model}, ContentType ID: {p.content_type.id}")
        else:
            self.stdout.write(self.style.SUCCESS("\nNenhuma permissão duplicada encontrada (mesmo codename + name)."))
        
        # Verificar se há ContentTypes duplicados para o mesmo modelo
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("VERIFICANDO CONTENT TYPES DUPLICADOS")
        self.stdout.write("=" * 60)
        
        cts_duplicados = ContentType.objects.filter(app_label__in=meus_apps).values('app_label', 'model').annotate(count=Count('id')).filter(count__gt=1)
        
        if cts_duplicados.exists():
            self.stdout.write(self.style.WARNING(f"\nEncontrados {cts_duplicados.count()} ContentTypes duplicados:\n"))
            
            for ct in cts_duplicados:
                app_label = ct['app_label']
                model = ct['model']
                count = ct['count']
                
                self.stdout.write(f"\n  App: {app_label}, Model: {model}, Quantidade: {count}")
                
                detalhes = ContentType.objects.filter(app_label=app_label, model=model)
                for c in detalhes:
                    self.stdout.write(f"    - ID: {c.id}, App: {c.app_label}, Model: {c.model}")
        else:
            self.stdout.write(self.style.SUCCESS("\nNenhum ContentType duplicado encontrado."))
        
        # Resumo final
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("RESUMO")
        self.stdout.write("=" * 60)
        
        total = Permission.objects.filter(content_type__app_label__in=meus_apps).count()
        self.stdout.write(f"Total de permissões nos apps: {total}")
        
        # Verificar se usar distinct() reduz o número
        total_distinct = Permission.objects.filter(content_type__app_label__in=meus_apps).distinct().count()
        self.stdout.write(f"Total de permissões únicas (distinct): {total_distinct}")
        
        if total != total_distinct:
            self.stdout.write(self.style.WARNING(f"\n⚠️ Há {total - total_distinct} permissões duplicadas que podem ser removidas com distinct()."))
