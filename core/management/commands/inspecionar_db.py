import getpass
import re
from django.core.management.base import BaseCommand
from django.db import transaction
import mysql.connector
from usuarios.models import Perfil, Usuario
from presenca.models import MotivoAusencia, Presenca, DiaNaoUtil

# --- MAPA DE-PARA ---
# Este dicionário usa os nomes das tabelas NOVAS como chaves
# e os nomes das tabelas ANTIGAS como valores.
MAPEAMENTO_TABELAS = {
    'usuarios_perfil': 'usuarios_perfil',
    'usuarios_usuario': 'usuarios',
    'presenca_motivoausencia': 'motivo_ausencia',
    'presenca_presenca': 'registros_presenca',
    'presenca_dianaoutil': 'dias_nao_uteis',
}

class Command(BaseCommand):
    help = 'Migra dados de um banco de dados antigo para o novo esquema.'

    def _conectar_banco_antigo(self):
        self.stdout.write("\nPor favor, insira as credenciais do banco de dados ANTIGO:")
        host = input("Host do Banco Antigo: ")
        database = input("Nome do Banco Antigo: ")
        user = input("Usuário do Banco Antigo: ")
        password = getpass.getpass("Senha do Banco Antigo: ")
        port = input("Porta (padrão 3306): ") or '3306'
        
        try:
            self.stdout.write(self.style.NOTICE(f"Conectando ao banco de dados antigo '{database}'..."))
            conn = mysql.connector.connect(
                host=host,
                database=database,
                user=user,
                password=password,
                port=port
            )
            self.stdout.write(self.style.SUCCESS("Conexão com o banco antigo bem-sucedida!"))
            return conn
        except mysql.connector.Error as err:
            self.stderr.write(self.style.ERROR(f"Erro ao conectar ao banco antigo: {err}"))
            return None

    def _gerar_username_unico(self, email):
        """Gera um username único a partir de um e-mail."""
        if not email:
            return None
        
        base_username = email.split('@')[0]
        # Remove caracteres especiais, deixando apenas letras e números
        username = re.sub(r'[^a-zA-Z0-9]', '', base_username).lower()
        
        if not username: # Caso o e-mail não tenha caracteres válidos antes do @
             username = 'usuario'

        # Garante a unicidade
        counter = 1
        final_username = username
        while Usuario.objects.filter(username=final_username).exists():
            final_username = f"{username}{counter}"
            counter += 1
            
        return final_username

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- INICIANDO SCRIPT DE MIGRAÇÃO DE DADOS ---"))
        
        conn = self._conectar_banco_antigo()
        if not conn:
            return

        cursor = conn.cursor(dictionary=True)
        
        # Mapa para relacionar IDs antigos com os novos
        id_map = {
            'perfis': {},
            'usuarios': {},
            'motivos': {}
        }

        try:
            with transaction.atomic():
                # 1. Migrar Perfis
                self.stdout.write("\nMigrando Perfis...")
                tabela_perfis_antiga = MAPEAMENTO_TABELAS['usuarios_perfil']
                cursor.execute(f"SELECT * FROM {tabela_perfis_antiga}")
                perfis_antigos = cursor.fetchall()

                for perfil_antigo in perfis_antigos:
                    novo_perfil, created = Perfil.objects.get_or_create(
                        nome=perfil_antigo['nome'],
                        defaults={'descricao': perfil_antigo.get('descricao', '')}
                    )
                    id_map['perfis'][perfil_antigo['id']] = novo_perfil.id
                    if created:
                        self.stdout.write(f"  Perfil '{novo_perfil.nome}' criado.")
                self.stdout.write(f"{len(perfis_antigos)} perfis processados.")

                # 2. Migrar Usuários
                self.stdout.write("\nMigrando Usuários...")
                tabela_usuarios_antiga = MAPEAMENTO_TABELAS['usuarios_usuario']
                cursor.execute(f"SELECT * FROM {tabela_usuarios_antiga}")
                usuarios_antigos = cursor.fetchall()

                for usuario_antigo in usuarios_antigos:
                    # Lógica para gerar username a partir do email
                    username = self._gerar_username_unico(usuario_antigo.get('email'))
                    if not username:
                        self.stdout.write(self.style.WARNING(f"  AVISO: Usuário com ID antigo {usuario_antigo['id']} não tem e-mail. A ser ignorado."))
                        continue
                    
                    # Se o usuário já existir (pelo username ou email), ignora
                    if Usuario.objects.filter(username=username).exists() or Usuario.objects.filter(email=usuario_antigo['email']).exists():
                        self.stdout.write(f"  Usuário '{username}' já existe. A ser ignorado.")
                        continue

                    perfil_id_antigo = usuario_antigo.get('perfil_id')
                    novo_perfil_id = id_map['perfis'].get(perfil_id_antigo)

                    # CORREÇÃO: Cria o usuário e define a senha separadamente para garantir o hash correto.
                    novo_usuario = Usuario.objects.create(
                        username=username,
                        email=usuario_antigo.get('email'),
                        first_name=usuario_antigo.get('first_name', ''),
                        last_name=usuario_antigo.get('last_name', ''),
                        is_staff=usuario_antigo.get('is_staff', False),
                        is_active=usuario_antigo.get('is_active', True),
                        is_superuser=usuario_antigo.get('is_superuser', False),
                        date_joined=usuario_antigo.get('date_joined'),
                        perfil_id=novo_perfil_id,
                        cpf=usuario_antigo.get('cpf')
                    )
                    novo_usuario.set_password('suasenhatemporaria123') # Define uma senha temporária
                    novo_usuario.save()
                    
                    self.stdout.write(f"  Usuário '{username}' criado com senha temporária. Por favor, instrua-o a redefini-la.")

                    id_map['usuarios'][usuario_antigo['id']] = novo_usuario.id
                
                self.stdout.write(f"{len(usuarios_antigos)} usuários processados.")
                
                # ... (adicionar migração de outras tabelas como presenca_motivoausencia, etc., se necessário)

                # 3. Migrar Presenças
                self.stdout.write("\nMigrando Presenças...")
                tabela_presencas_antiga = MAPEAMENTO_TABELAS['presenca_presenca']
                cursor.execute(f"SELECT * FROM {tabela_presencas_antiga}")
                presencas_antigas = cursor.fetchall()

                for presenca_antiga in presencas_antigas:
                    colaborador_id_antigo = presenca_antiga.get('colaborador_id')
                    lancado_por_id_antigo = presenca_antiga.get('lancado_por_id')
                    
                    novo_colaborador_id = id_map['usuarios'].get(colaborador_id_antigo)
                    novo_lancado_por_id = id_map['usuarios'].get(lancado_por_id_antigo)

                    # Se o colaborador original não foi migrado, não podemos criar a presença
                    if not novo_colaborador_id:
                        continue

                    Presenca.objects.create(
                        colaborador_id=novo_colaborador_id,
                        data=presenca_antiga.get('data'),
                        presente=presenca_antiga.get('presente', False),
                        # Adicionar mapeamento de outros campos se necessário
                        # motivo_id=...
                        lancado_por_id=novo_lancado_por_id,
                    )
                self.stdout.write(f"{len(presencas_antigas)} presenças processadas.")

            self.stdout.write(self.style.SUCCESS("\n--- MIGRAÇÃO CONCLUÍDA COM SUCESSO! ---"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\nOcorreu um erro inesperado durante a migração: {e}"))
        
        finally:
            if conn and conn.is_connected():
                cursor.close()
                conn.close()
                self.stdout.write("Conexão com o banco antigo fechada.")