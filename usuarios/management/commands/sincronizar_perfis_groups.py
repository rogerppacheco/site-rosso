from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from usuarios.models import Usuario, Perfil

class Command(BaseCommand):
    help = 'Sincroniza o campo perfil (ForeignKey) baseado nos Groups atribuídos aos usuários'

    def handle(self, *args, **options):
        self.stdout.write("=" * 80)
        self.stdout.write("SINCRONIZANDO PERFIS BASEADO EM GROUPS")
        self.stdout.write("=" * 80)
        
        usuarios = Usuario.objects.all()
        atualizados = 0
        sem_perfil = 0
        
        for usuario in usuarios:
            # Pegar o primeiro grupo do usuário (ou None se não tiver)
            primeiro_grupo = usuario.groups.first()
            
            if primeiro_grupo:
                # Tentar encontrar um Perfil com o mesmo nome do Group
                try:
                    perfil = Perfil.objects.get(nome=primeiro_grupo.name)
                    if usuario.perfil != perfil:
                        usuario.perfil = perfil
                        usuario.save()
                        atualizados += 1
                        self.stdout.write(f"✅ {usuario.username}: Group '{primeiro_grupo.name}' → Perfil '{perfil.nome}'")
                    else:
                        self.stdout.write(f"ℹ️  {usuario.username}: Já está sincronizado (Group '{primeiro_grupo.name}' = Perfil '{perfil.nome}')")
                except Perfil.DoesNotExist:
                    # Não encontrou Perfil com esse nome
                    if usuario.perfil:
                        # Limpa o perfil se tinha um antes
                        usuario.perfil = None
                        usuario.save()
                        self.stdout.write(self.style.WARNING(f"⚠️  {usuario.username}: Group '{primeiro_grupo.name}' não tem Perfil correspondente. Campo perfil limpo."))
                        sem_perfil += 1
                    else:
                        self.stdout.write(self.style.WARNING(f"⚠️  {usuario.username}: Group '{primeiro_grupo.name}' não tem Perfil correspondente."))
                        sem_perfil += 1
            else:
                # Usuário não tem grupos
                if usuario.perfil:
                    # Limpa o perfil se tinha um antes
                    usuario.perfil = None
                    usuario.save()
                    self.stdout.write(self.style.WARNING(f"⚠️  {usuario.username}: Sem grupos. Campo perfil limpo."))
                    sem_perfil += 1
                else:
                    self.stdout.write(f"ℹ️  {usuario.username}: Sem grupos e sem perfil (já estava assim)")
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(f"✅ Total de {atualizados} usuário(s) sincronizado(s)"))
        if sem_perfil > 0:
            self.stdout.write(self.style.WARNING(f"⚠️  {sem_perfil} usuário(s) sem Perfil correspondente ao Group"))
        self.stdout.write("=" * 80)
