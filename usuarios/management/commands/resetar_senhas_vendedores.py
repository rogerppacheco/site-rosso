from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from usuarios.models import Perfil

Usuario = get_user_model()

class Command(BaseCommand):
    help = 'Reseta a senha de todos os usuários com perfil Vendedor para uma senha padrão.'

    def add_arguments(self, parser):
        # Permite passar a senha via linha de comando (opcional)
        parser.add_argument(
            '--senha', 
            type=str, 
            help='A nova senha padrão a ser definida', 
            default='Mudar123' # SENHA PADRÃO SE NÃO INFORMAR OUTRA
        )

    def handle(self, *args, **options):
        nova_senha = options['senha']
        
        self.stdout.write(f"Iniciando reset para senha padrão: '{nova_senha}'...")

        # 1. Busca o Perfil (Tenta 'Vendedor', 'vendedor', 'Consultor', etc)
        # Ajuste o nome abaixo exatamente como está no seu banco de dados
        nome_perfil = 'Vendedor' 
        
        try:
            # Busca insensível a maiúsculas/minúsculas
            perfil = Perfil.objects.get(nome__iexact=nome_perfil)
        except Perfil.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"ERRO: Perfil '{nome_perfil}' não encontrado no banco de dados."))
            return

        # 2. Filtra Usuários
        usuarios = Usuario.objects.filter(perfil=perfil)
        count = usuarios.count()

        if count == 0:
            self.stdout.write(self.style.WARNING(f"Nenhum usuário encontrado com o perfil '{perfil.nome}'."))
            return

        # 3. Aplica a mudança em massa
        confirmacao = input(f"Encontrados {count} usuários com perfil '{perfil.nome}'. Tem certeza? [S/N]: ")
        
        if confirmacao.lower() != 's':
            self.stdout.write(self.style.WARNING("Operação cancelada."))
            return

        self.stdout.write("Processando...")
        
        sucessos = 0
        for u in usuarios:
            try:
                u.set_password(nova_senha)
                u.obriga_troca_senha = True  # FORÇA A TROCA NO PRÓXIMO LOGIN
                u.save()
                sucessos += 1
                # self.stdout.write(f" - Senha alterada para: {u.username}") # Descomente se quiser ver lista
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erro ao salvar {u.username}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"CONCLUÍDO! {sucessos} usuários atualizados com sucesso."))
        self.stdout.write(self.style.SUCCESS(f"Senha padrão: {nova_senha}"))
        self.stdout.write(self.style.SUCCESS(f"Todos foram marcados para troca obrigatória de senha."))