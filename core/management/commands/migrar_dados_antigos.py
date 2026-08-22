import getpass
import re
import traceback
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone
import mysql.connector

# Importe todos os modelos necessários
from usuarios.models import Perfil, Usuario
from presenca.models import MotivoAusencia, Presenca, DiaNaoUtil

# --- MAPA DE-PARA FINAL E CORRIGIDO ---
MAPEAMENTO_TABELAS = {
    'usuarios_perfil': 'usuarios_perfil',
    'usuarios_usuario': 'usuarios',
    'presenca_motivoausencia': 'motivos_ausencia',
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
                port=port,
                charset='utf8'
            )
            self.stdout.write(self.style.SUCCESS("Conexão com o banco antigo bem-sucedida!"))
            return conn
        except mysql.connector.Error as err:
            self.stderr.write(self.style.ERROR(f"Erro ao conectar ao banco antigo: {err}"))
            return None

    def _gerar_username_unico(self, email):
        if not email:
            return None
        base_username = email.split('@')[0]
        username = re.sub(r'[^a-zA-Z0-9]', '', base_username).lower()
        if not username:
             username = 'usuario'
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
        id_map = {'perfis': {}, 'usuarios': {}, 'motivos': {}}

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
                    email_antigo = usuario_antigo.get('email')
                    cpf_antigo = usuario_antigo.get('cpf')
                    username = self._gerar_username_unico(email_antigo)
                    
                    if not email_antigo:
                        self.stdout.write(self.style.WARNING(f"  AVISO: Usuário com ID antigo {usuario_antigo['id']} não tem e-mail. A ser ignorado."))
                        continue

                    # --- LÓGICA ANTI-DUPLICAÇÃO MELHORADA ---
                    condicoes = Q(username=username) | Q(email=email_antigo)
                    if cpf_antigo:
                        condicoes |= Q(cpf=cpf_antigo)
                    
                    usuario_existente = Usuario.objects.filter(condicoes).first()
                    if usuario_existente:
                        self.stdout.write(self.style.WARNING(f"  AVISO: Usuário '{username}' (e-mail ou CPF) já existe. A ser ignorado."))
                        # Mesmo que o usuário já exista, precisamos de mapear o seu ID para as presenças
                        id_map['usuarios'][usuario_antigo['id']] = usuario_existente.id
                        continue
                    # --- FIM DA LÓGICA ANTI-DUPLICAÇÃO ---

                    data_joined = usuario_antigo.get('data_admissao') or timezone.now()
                    nome_completo = usuario_antigo.get('nome_completo', '').strip()
                    partes_nome = nome_completo.split(' ', 1)
                    first_name = partes_nome[0]
                    last_name = partes_nome[1] if len(partes_nome) > 1 else ''
                    perfil_id_antigo = usuario_antigo.get('perfil_id')
                    novo_perfil_id = id_map['perfis'].get(perfil_id_antigo)

                    novo_usuario = Usuario.objects.create(
                        username=username,
                        email=email_antigo,
                        first_name=first_name,
                        last_name=last_name,
                        is_staff=False,
                        is_active=True if usuario_antigo.get('status') == 1 else False,
                        is_superuser=False,
                        date_joined=data_joined,
                        perfil_id=novo_perfil_id,
                        cpf=cpf_antigo
                    )
                    novo_usuario.set_unusable_password()
                    novo_usuario.save()

                    id_map['usuarios'][usuario_antigo['id']] = novo_usuario.id
                
                self.stdout.write(f"{len(usuarios_antigos)} usuários processados.")
                
                # 3. Migrar Motivos de Ausência
                self.stdout.write("\nMigrando Motivos de Ausência...")
                tabela_motivos_antiga = MAPEAMENTO_TABELAS['presenca_motivoausencia']
                cursor.execute(f"SELECT * FROM {tabela_motivos_antiga}")
                motivos_antigos = cursor.fetchall()

                for motivo_antigo in motivos_antigos:
                    novo_motivo, created = MotivoAusencia.objects.get_or_create(
                        motivo=motivo_antigo['motivo']
                    )
                    id_map['motivos'][motivo_antigo['id']] = novo_motivo.id
                self.stdout.write(f"{len(motivos_antigos)} motivos processados.")

                # 4. Migrar Dias Não Úteis
                self.stdout.write("\nMigrando Dias Não Úteis...")
                tabela_dias_antiga = MAPEAMENTO_TABELAS['presenca_dianaoutil']
                cursor.execute(f"SELECT * FROM {tabela_dias_antiga}")
                dias_antigos = cursor.fetchall()

                for dia_antigo in dias_antigos:
                    DiaNaoUtil.objects.get_or_create(
                        data=dia_antigo['data'],
                        defaults={'descricao': dia_antigo.get('descricao', '')}
                    )
                self.stdout.write(f"{len(dias_antigos)} dias não úteis processados.")

                # 5. Migrar Presenças
                self.stdout.write("\nMigrando Registros de Presença...")
                tabela_presencas_antiga = MAPEAMENTO_TABELAS['presenca_presenca']
                cursor.execute(f"SELECT * FROM {tabela_presencas_antiga}")
                presencas_antigas = cursor.fetchall()

                for presenca_antiga in presencas_antigas:
                    id_colaborador_antigo = presenca_antiga.get('vendedor_id')
                    novo_colaborador_id = id_map['usuarios'].get(id_colaborador_antigo)
                    
                    novo_lancado_por_id = id_map['usuarios'].get(presenca_antiga.get('lancado_por_id'))
                    novo_motivo_id = id_map['motivos'].get(presenca_antiga.get('motivo_id'))

                    if not novo_colaborador_id:
                        self.stdout.write(self.style.WARNING(f"  AVISO: Colaborador com ID antigo {id_colaborador_antigo} não encontrado para o registro de presença ID {presenca_antiga['id']}. A ser ignorado."))
                        continue

                    try:
                        Presenca.objects.create(
                            data=presenca_antiga['data'],
                            observacao=presenca_antiga.get('observacao', ''),
                            colaborador_id=novo_colaborador_id,
                            lancado_por_id=novo_lancado_por_id,
                            motivo_id=novo_motivo_id
                        )
                    except IntegrityError:
                        self.stdout.write(self.style.WARNING(f"  AVISO: Registro de presença para o colaborador ID {novo_colaborador_id} na data {presenca_antiga['data']} já existe. A ser ignorado."))
                        continue

                self.stdout.write(f"{len(presencas_antigas)} registros de presença processados.")

            self.stdout.write(self.style.SUCCESS("\n--- MIGRAÇÃO COMPLETA CONCLUÍDA COM SUCESSO! ---"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\nOcorreu um erro inesperado durante a migração: {e}"))
            self.stderr.write(self.style.ERROR("--- DETALHES COMPLETOS DO ERRO ---"))
            traceback.print_exc()
            self.stderr.write(self.style.ERROR("----------------------------------"))
        
        finally:
            if conn and conn.is_connected():
                cursor.close()
                conn.close()
                self.stdout.write("Conexão com o banco antigo fechada.")