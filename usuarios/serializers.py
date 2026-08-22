from rest_framework import serializers
from .models import Usuario, Perfil, PermissaoPerfil
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import Permission, Group
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

# --- SERIALIZERS DE SEGURANÇA ---

class TrocaSenhaSerializer(serializers.Serializer):
    """
    Serializer para a troca obrigatória de senha.
    """
    nova_senha = serializers.CharField(required=True, min_length=6)
    confirmacao_senha = serializers.CharField(required=True, min_length=6)

    def validate(self, data):
        if data['nova_senha'] != data['confirmacao_senha']:
            raise serializers.ValidationError("As senhas não conferem.")
        return data

class ResetSenhaSolicitacaoSerializer(serializers.Serializer):
    """
    Serializer para solicitar reset via "Esqueci minha senha".
    """
    cpf = serializers.CharField(required=True)
    whatsapp = serializers.CharField(required=True)

# --- SERIALIZERS DE PERMISSÃO E GRUPO ---

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'name', 'codename']

class GroupSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all())
    permissions_details = PermissionSerializer(source='permissions', many=True, read_only=True)

    class Meta:
        model = Group
        fields = ['id', 'name', 'permissions', 'permissions_details']

# --- SERIALIZERS AUXILIARES ---

class RecursoSerializer(serializers.Serializer):
    recurso = serializers.CharField()
    def to_representation(self, instance):
        return instance

class PerfilSerializer(serializers.ModelSerializer):
    def validate_cod_perfil(self, value):
        if not value:
            raise serializers.ValidationError("O campo 'cod_perfil' é obrigatório.")
        if Perfil.objects.filter(cod_perfil=value).exists():
            raise serializers.ValidationError("Já existe um perfil com este código.")
        return value

    class Meta:
        model = Perfil
        fields = ['id', 'nome', 'cod_perfil']

class UsuarioLiderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ['id', 'username', 'first_name', 'last_name', 'email']

class UsuarioSerializer(serializers.ModelSerializer):
    # Campos de leitura
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)
    perfil_detalhe = PerfilSerializer(source='perfil', read_only=True)
    supervisor_detalhe = UsuarioLiderSerializer(source='supervisor', read_only=True)
    groups_detalhe = GroupSerializer(source='groups', many=True, read_only=True)
    supervisor_nome = serializers.SerializerMethodField()
    brpronto_senha_preenchida = serializers.SerializerMethodField()

    # MÉTODO PARA OBTER O NOME DO LÍDER
    def get_supervisor_nome(self, obj):
        if obj.supervisor:
            nome = f"{obj.supervisor.first_name} {obj.supervisor.last_name}".strip()
            return nome if nome else obj.supervisor.username
        return "-"

    def get_brpronto_senha_preenchida(self, obj) -> bool:
        return bool(getattr(obj, "brpronto_senha", None))

    def validate_meta_comissao(self, value):
        """Valida e normaliza meta_comissao - aceita 0 como valor válido"""
        if value is None or value == '':
            return 0
        if isinstance(value, str):
            try:
                # Converte string para int, tratando "0" corretamente
                return int(value)
            except (ValueError, TypeError):
                return 0
        # Aceita 0 como valor válido (0 é um número válido)
        return value if value is not None else 0

    def validate(self, attrs):
        attrs = super().validate(attrs)
        perfil = attrs.get('perfil', getattr(self.instance, 'perfil', None))
        perfil_nome = (getattr(perfil, 'nome', '') or '').strip().lower()
        if perfil_nome != 'vendedor':
            attrs['vendedor_solo'] = False
        return attrs

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'matricula_pap', 'senha_pap',
            'perfil', 'perfil_detalhe',
            'groups', 'groups_detalhe',
            'supervisor', 'supervisor_detalhe', 'supervisor_nome',
            'valor_almoco', 'valor_passagem', 'valor_ajuda_custo_mensal', 'chave_pix', 'nome_da_conta',
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 
            'adiantamento_cnpj', 'recebe_adiantamento_cnpj', 'recebe_adiantamento_sabado', 'desconto_inss_fixo',
            'is_active', 'is_staff',
            'canal',
            'cluster',
            'participa_controle_presenca',
            'vendedor_solo',
            'autorizar_venda_sem_auditoria',
            'autorizar_venda_automatica',
            'autorizar_analise_credito_wpp',
            'autorizar_inclusao_wpp',
            'autorizado_chamar_no_bot',
            'login_pap_disponivel_para_automacao',
            'pap_automacao_vender',
            'pap_automacao_credito',
            'pap_automacao_pedido',
            'pap_automacao_status',
            'pode_gestao_acessos',
            'brpronto_login',
            'brpronto_senha',
            'brpronto_senha_preenchida',
            'brpronto_dominio',
            'brpronto_disponivel_para_automacao',
            'autorizar_consulta_bio_wpp',
            'tel_whatsapp',
            'tel_whatsapp_2',
            'tel_whatsapp_3',
            'obriga_troca_senha',
            'password'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'brpronto_senha': {'write_only': True, 'required': False},
            'perfil': {'required': False, 'allow_null': True},
            'supervisor': {'required': False, 'allow_null': True},
            'meta_comissao': {'required': False, 'allow_null': True},
        }

    def to_representation(self, instance):
        """
        Transforma a resposta para o Frontend.
        Quando o front pede a lista, ele recebe o objeto Perfil inteiro (com nome),
        não apenas o ID.
        """
        ret = super().to_representation(instance)
        
        # Injeta os detalhes do perfil (com tratamento de erro caso perfil não exista)
        try:
            if instance.perfil_id and instance.perfil:
                ret['perfil'] = PerfilSerializer(instance.perfil).data
        except Exception:
            # Se o perfil não existir (ID inválido), não inclui no retorno
            pass
        
        # Injeta os detalhes do supervisor (Líder)
        try:
            if instance.supervisor_id and instance.supervisor:
                ret['supervisor'] = UsuarioLiderSerializer(instance.supervisor).data
        except Exception:
            # Se o supervisor não existir, não inclui no retorno
            pass
            
        return ret

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        groups = validated_data.pop('groups', [])
        
        # Garantir que campos com default não sejam None ou string vazia
        if 'meta_comissao' in validated_data:
            if validated_data['meta_comissao'] is None or validated_data['meta_comissao'] == '':
                validated_data['meta_comissao'] = 0
            elif isinstance(validated_data['meta_comissao'], str):
                # Converte string para int (aceita "0" como valor válido)
                try:
                    validated_data['meta_comissao'] = int(validated_data['meta_comissao'])
                except (ValueError, TypeError):
                    validated_data['meta_comissao'] = 0
        
        instance = self.Meta.model(**validated_data)
        if password:
            instance.set_password(password)
            instance.obriga_troca_senha = True
        
        # Se perfil foi definido, sincroniza grupo baseado no perfil (perfil é fonte de verdade)
        if 'perfil' in validated_data and validated_data.get('perfil'):
            try:
                self._sincronizar_grupo_do_perfil(instance)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Erro ao sincronizar grupo do perfil: {e}")
        # Se não tem perfil mas tem groups, sincroniza perfil baseado no grupo
        elif groups:
            try:
                first_group = groups[0]
                group_id = first_group.id if hasattr(first_group, 'id') else first_group
                self._sincronizar_perfil_do_group(instance, group_id)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Erro ao sincronizar perfil do grupo: {e}")
        
        instance.save()
        if (getattr(instance.perfil, 'nome', '') or '').strip().lower() != 'vendedor' and instance.vendedor_solo:
            instance.vendedor_solo = False
            instance.save(update_fields=['vendedor_solo'])
        if groups:
            instance.groups.set(groups)
        return instance

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        groups = validated_data.pop('groups', None)
        
        # Garantir que campos com default não sejam None ou string vazia
        if 'meta_comissao' in validated_data:
            if validated_data['meta_comissao'] is None or validated_data['meta_comissao'] == '':
                validated_data['meta_comissao'] = 0
            elif isinstance(validated_data['meta_comissao'], str):
                # Converte string para int (aceita "0" como valor válido)
                try:
                    validated_data['meta_comissao'] = int(validated_data['meta_comissao'])
                except (ValueError, TypeError):
                    validated_data['meta_comissao'] = 0
        
        # Captura o perfil antes de atualizar (para verificar se mudou)
        perfil_anterior = instance.perfil
        perfil_alterado = 'perfil' in validated_data
        
        # Atualiza campos normais (groups já foi removido do validated_data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Se o perfil foi alterado, sincroniza o grupo baseado no perfil (perfil é fonte de verdade)
        if perfil_alterado:
            self._sincronizar_grupo_do_perfil(instance)
        # Se groups foi alterado (mas perfil não), sincroniza perfil baseado no grupo
        elif groups is not None:
            instance.groups.set(groups)
            # Sincronizar campo perfil baseado no primeiro grupo
            first_group = groups[0] if groups else None
            if first_group:
                group_id = first_group.id if hasattr(first_group, 'id') else first_group
            else:
                group_id = None
            self._sincronizar_perfil_do_group(instance, group_id)
            
        # Atualiza senha se fornecida
        if password:
            instance.set_password(password)
            
        instance.save()
        if (getattr(instance.perfil, 'nome', '') or '').strip().lower() != 'vendedor' and instance.vendedor_solo:
            instance.vendedor_solo = False
            instance.save(update_fields=['vendedor_solo'])
        return instance
    
    def _sincronizar_grupo_do_perfil(self, usuario):
        """
        Sincroniza os grupos baseado no perfil (perfil é a fonte de verdade).
        Define apenas o grupo correspondente ao perfil, removendo outros.
        """
        from django.contrib.auth.models import Group
        
        if usuario.perfil:
            try:
                # Busca o grupo com o mesmo nome do perfil
                group = Group.objects.get(name__iexact=usuario.perfil.nome)
                # Define apenas este grupo (remove outros e adiciona este)
                usuario.groups.set([group])
            except Group.DoesNotExist:
                # Se não encontrar grupo correspondente, limpa os grupos
                usuario.groups.clear()
        else:
            # Se perfil está vazio, limpa os grupos
            usuario.groups.clear()
    
    def _sincronizar_perfil_do_group(self, usuario, group_id):
        """
        Sincroniza o campo perfil (ForeignKey) baseado no Group atribuído.
        Busca um Perfil com nome igual ao nome do Group.
        """
        from django.contrib.auth.models import Group
        from usuarios.models import Perfil
        
        if not group_id:
            # Se não há grupo, limpa o perfil
            usuario.perfil = None
            return
        
        try:
            group = Group.objects.get(id=group_id)
            # Busca um Perfil com o mesmo nome do Group (case-insensitive)
            try:
                perfil = Perfil.objects.get(nome__iexact=group.name)
                usuario.perfil = perfil
            except Perfil.DoesNotExist:
                # Se não encontrar Perfil com esse nome, limpa o campo
                usuario.perfil = None
                # Log para debug
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Perfil '{group.name}' não encontrado para Group '{group.name}'. Campo perfil limpo.")
            except Perfil.MultipleObjectsReturned:
                # Se houver múltiplos perfis com o mesmo nome, pega o primeiro
                perfil = Perfil.objects.filter(nome__iexact=group.name).first()
                usuario.perfil = perfil
        except Group.DoesNotExist:
            # Se o Group não existir, limpa o perfil
            usuario.perfil = None
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Group com ID {group_id} não encontrado. Campo perfil limpo.")

# --- SERIALIZER DE PERFIL DO USUÁRIO (LEITURA) ---

class UserProfileSerializer(serializers.ModelSerializer):
    perfil_nome = serializers.CharField(source='perfil.nome', read_only=True)
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, default=None)
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)
    groups = GroupSerializer(many=True, read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'perfil', 'perfil_nome', 'groups',
            'supervisor', 'supervisor_nome',
            'is_active', 'is_staff',
            'tel_whatsapp',
            'tel_whatsapp_2',
            'tel_whatsapp_3',
            'obriga_troca_senha',
            'pode_gestao_acessos',
            'vendedor_solo',
        ]

# --- SERIALIZER DE LOGIN (CUSTOMIZADO) ---

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['user_name'] = user.get_full_name() if hasattr(user, 'get_full_name') else user.username
        
        # Super usuários sempre recebem 'Admin' para acesso total
        if user.is_superuser:
            perfil_nome = 'Admin'
        else:
            # Adiciona o perfil legado (com tratamento de erro caso perfil não exista)
            perfil_nome = 'Vendedor'  # Padrão
            try:
                # Prioridade 1: Campo perfil do modelo Usuario
                if hasattr(user, 'perfil_id') and user.perfil_id:
                    user.perfil  # Tenta acessar para verificar se existe
                    if user.perfil:
                        perfil_nome = user.perfil.nome
            except Exception:
                pass
            
            # Prioridade 2: Se não encontrou perfil, usa o primeiro Group como fallback
            if perfil_nome == 'Vendedor' and user.groups.exists():
                perfil_nome = user.groups.first().name
        
        token['perfil'] = perfil_nome
        token['user_role'] = perfil_nome  # Compatibilidade com frontend
        token['is_superuser'] = bool(user.is_superuser)
        
        # Adiciona o primeiro grupo como perfil principal
        if user.groups.exists():
            token['grupo_principal'] = user.groups.first().name
        # --- SEGURANÇA: Adiciona flag no Token ---
        token['obriga_troca_senha'] = user.obriga_troca_senha
        token['autorizar_venda_automatica'] = getattr(user, 'autorizar_venda_automatica', False)
        token['pode_gestao_acessos'] = getattr(user, 'pode_gestao_acessos', False)
        token['vendedor_solo'] = getattr(user, 'vendedor_solo', False)
        return token

    def validate(self, attrs):
        # Permitir login com username OU email
        username_input = attrs.get('username', '')
        password = attrs.get('password', '')
        
        logger.warning(f"[LOGIN] Input: username_input='{username_input}', password_len={len(password) if password else 0}")
        
        # Tentar primeiro com o valor fornecido (username ou email)
        self.user = None
        try:
            # Tenta com username primeiro (case-insensitive)
            self.user = User.objects.get(username__iexact=username_input)
            logger.warning(f"[LOGIN] Found user by username: {self.user.username}")
        except User.DoesNotExist:
            logger.warning(f"[LOGIN] User not found by username, trying email...")
            try:
                # Se não encontrar, tenta com email (case-insensitive)
                self.user = User.objects.get(email__iexact=username_input)
                logger.warning(f"[LOGIN] Found user by email: {self.user.username}")
            except User.DoesNotExist:
                logger.warning(f"[LOGIN] User not found by email either")
                pass
        
        # Se encontrou usuário, atualizar attrs para autenticação do Django
        if self.user:
            attrs['username'] = self.user.username
            logger.warning(f"[LOGIN] Updated attrs username to: {attrs['username']}")
        
        try:
            logger.warning(f"[LOGIN] Calling super().validate()...")
            data = super().validate(attrs)
            logger.warning(f"[LOGIN] super().validate() succeeded")
        except Exception as e:
            logger.warning(f"[LOGIN] super().validate() failed: {type(e).__name__}: {str(e)}")
            raise

        if self.user and not self.user.is_active:
            raise serializers.ValidationError("Este usuário está inativo e não pode fazer login.")

        data['token'] = data.pop('access')

        user_profile = None
        if self.user:
            try:
                # Tenta acessar o perfil, mas não falha se não existir
                if self.user.perfil_id:  # Verifica se há um ID antes de acessar
                    user_profile = self.user.perfil.nome
            except Exception as e:
                logger.warning(f"[LOGIN] Erro ao acessar perfil: {e}")
                user_profile = None

        # --- RETORNA A FLAG PARA O JAVASCRIPT ---
        if self.user:
            data['obriga_troca_senha'] = self.user.obriga_troca_senha 

            data['user'] = {
                'id': self.user.id,
                'username': self.user.username,
                'perfil': user_profile,
                'groups': [g.name for g in self.user.groups.all()],
                'obriga_troca_senha': self.user.obriga_troca_senha,
                'vendedor_solo': getattr(self.user, 'vendedor_solo', False),
                'is_superuser': bool(getattr(self.user, 'is_superuser', False)),
            }
        
        return data