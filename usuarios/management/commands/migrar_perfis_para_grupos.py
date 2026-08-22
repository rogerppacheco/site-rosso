from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from usuarios.models import Usuario

class Command(BaseCommand):
    help = 'Migra usuários do campo Perfil (legado) para os Grupos do Django automaticamente.'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando migração de perfis...")
        
        usuarios = Usuario.objects.all()
        migrados = 0
        
        for user in usuarios:
            # Verifica se o usuário tem um perfil legado vinculado
            if user.perfil:
                nome_perfil = user.perfil.nome
                
                # Cria ou recupera o Grupo com o mesmo nome do Perfil
                grupo, created = Group.objects.get_or_create(name=nome_perfil)
                
                if created:
                    self.stdout.write(f"Grupo criado: {nome_perfil}")
                
                # Se o usuário ainda não está no grupo, adiciona
                if not user.groups.filter(name=nome_perfil).exists():
                    user.groups.add(grupo)
                    migrados += 1
                    self.stdout.write(f" -> Usuário {user.username} adicionado ao grupo '{nome_perfil}'")
        
        self.stdout.write(self.style.SUCCESS(f'Concluído! Total de {migrados} usuários atualizados.'))