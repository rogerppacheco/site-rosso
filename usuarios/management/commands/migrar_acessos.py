from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from usuarios.models import Usuario

class Command(BaseCommand):
    help = 'Sincroniza os perfis antigos com os novos Grupos de Segurança'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando migração de acessos...")
        
        usuarios = Usuario.objects.all()
        alterados = 0

        for user in usuarios:
            if user.perfil:
                nome_perfil = user.perfil.nome
                
                # Tenta encontrar o Grupo com o mesmo nome do Perfil antigo
                try:
                    grupo = Group.objects.get(name=nome_perfil)
                    
                    # Se o usuário ainda não está no grupo, adiciona
                    if not user.groups.filter(name=nome_perfil).exists():
                        user.groups.add(grupo)
                        self.stdout.write(f" - Usuário '{user.username}' adicionado ao grupo '{nome_perfil}'")
                        alterados += 1
                except Group.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f" ! Grupo '{nome_perfil}' não existe para o usuário '{user.username}'"))

        self.stdout.write(self.style.SUCCESS(f"\nConcluído! {alterados} usuários atualizados."))