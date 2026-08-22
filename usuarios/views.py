from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth.models import ContentType, Group, Permission
from django.db import transaction, connection
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.http import HttpResponse
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from crm_app.whatsapp_service import WhatsAppService
from datetime import datetime
import re
import openpyxl

from .models import Usuario, Perfil, PermissaoPerfil
from .serializers import (
    UsuarioSerializer,
    PerfilSerializer,
    UserProfileSerializer,
    RecursoSerializer,
    CustomTokenObtainPairSerializer,
    GroupSerializer,
    PermissionSerializer,
    TrocaSenhaSerializer,
    ResetSenhaSolicitacaoSerializer
)

# Perfis que não aparecem na ferramenta Gestão de Acessos (delegação)
PERFIS_EXCLUIDOS_GESTAO_ACESSOS = ('Admin', 'Diretoria')


class PodeGestaoAcessos(permissions.BasePermission):
    """Só permite acesso se o usuário tiver pode_gestao_acessos=True no cadastro."""
    message = "Você não tem permissão para usar a Gestão de Acessos."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return getattr(request.user, 'pode_gestao_acessos', False)


class GestaoAcessosUsuarioViewSet(viewsets.ModelViewSet):
    """
    API de usuários restrita à ferramenta Gestão de Acessos.
    - Só acessível por quem tem pode_gestao_acessos=True.
    - Lista e edição nunca incluem usuários com perfil Admin ou Diretoria.
    - Não é permitido atribuir perfil/grupo Admin ou Diretoria a ninguém.
    """
    serializer_class = UsuarioSerializer
    permission_classes = [permissions.IsAuthenticated, PodeGestaoAcessos]

    def get_queryset(self):
        qs = (
            Usuario.objects.all()
            .select_related('supervisor', 'perfil')
            .prefetch_related('groups')
            .order_by('first_name')
        )
        # Excluir quem tem perfil Admin ou Diretoria (por perfil ou por grupo)
        qs = qs.exclude(
            Q(perfil__nome__in=PERFIS_EXCLUIDOS_GESTAO_ACESSOS)
            | Q(groups__name__in=PERFIS_EXCLUIDOS_GESTAO_ACESSOS)
        ).distinct()

        is_active_param = self.request.query_params.get('is_active')
        if is_active_param is not None:
            is_active_value = is_active_param.lower() in ('true', '1')
            qs = qs.filter(is_active=is_active_value)
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            q = Q(username__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search)
            qs = qs.filter(q)
        return qs

    def _grupos_proibidos_ids(self):
        return set(
            Group.objects.filter(name__in=PERFIS_EXCLUIDOS_GESTAO_ACESSOS).values_list('id', flat=True)
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.get('partial', False)
        groups = request.data.get('groups')
        if groups is not None:
            proibidos = self._grupos_proibidos_ids()
            if any(g in proibidos for g in (groups if isinstance(groups, list) else [])):
                return Response(
                    {'detail': 'Não é permitido atribuir perfil Admin ou Diretoria nesta ferramenta.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        return super().update(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        groups = request.data.get('groups')
        if groups is not None:
            proibidos = self._grupos_proibidos_ids()
            if any(g in proibidos for g in (groups if isinstance(groups, list) else [])):
                return Response(
                    {'detail': 'Não é permitido atribuir perfil Admin ou Diretoria nesta ferramenta.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=['put'], url_path='reativar')
    def reativar(self, request, pk=None):
        usuario = self.get_object()
        usuario.is_active = True
        usuario.save()
        return Response({'status': 'reativado'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def lideres(self, request):
        """Líderes (supervisores) visíveis na Gestão de Acessos: apenas não Admin/Diretoria."""
        qs = Usuario.objects.filter(is_active=True).exclude(
            Q(perfil__nome__in=PERFIS_EXCLUIDOS_GESTAO_ACESSOS)
            | Q(groups__name__in=PERFIS_EXCLUIDOS_GESTAO_ACESSOS)
        ).distinct()
        usuarios = qs.values('id', 'username', 'first_name', 'last_name')
        data = []
        for u in usuarios:
            nome = f"{u['first_name']} {u['last_name']}".strip()
            nome = nome or u['username']
            if f"{u['first_name']} {u['last_name']}".strip():
                nome = f"{nome} ({u['username']})"
            data.append({'id': u['id'], 'username': u['username'], 'nome_exibicao': nome})
        return Response(data)

    @action(detail=False, methods=['get'], url_path='exportar-excel')
    def exportar_excel(self, request):
        """
        Exporta usuários da Gestão de Acessos para Excel.
        Respeita os mesmos filtros da listagem (is_active e search).
        """
        queryset = self.filter_queryset(self.get_queryset()).order_by('first_name', 'username')

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Usuarios"

        headers = [
            "ID",
            "Ativo",
            "Nome completo",
            "Primeiro nome",
            "Sobrenome",
            "Username",
            "Email",
            "CPF",
            "Matricula PAP",
            "Senha PAP",
            "Perfil",
            "Lider",
            "Canal",
            "Cluster",
            "WhatsApp 1",
            "WhatsApp 2",
            "WhatsApp 3",
            "Br Pronto Login",
            "Br Pronto Senha",
            "Br Pronto Dominio",
            "Meta comissao",
            "Chave PIX",
            "Nome da conta",
            "Valor almoco",
            "Valor passagem",
            "Desconto boleto",
            "Desconto inclusao viabilidade",
            "Desconto instalacao antecipada",
            "Adiantamento CNPJ",
            "Desconto INSS fixo",
            "Participa controle presenca",
            "Vendedor solo",
            "Autorizar venda sem auditoria",
            "Autorizar venda automatica",
            "Autorizar analise credito WPP",
            "Autorizar inclusao WPP",
            "Login PAP disponivel automacao",
            "PAP automacao vender",
            "PAP automacao credito",
            "PAP automacao pedido",
            "PAP automacao status",
        ]
        ws.append(headers)

        def b(value):
            return "Sim" if bool(value) else "Nao"

        for u in queryset:
            nome_completo = f"{u.first_name or ''} {u.last_name or ''}".strip() or u.username
            perfil_nome = getattr(u.perfil, 'nome', '') or '-'
            lider_nome = '-'
            if u.supervisor:
                lider_nome = (f"{u.supervisor.first_name or ''} {u.supervisor.last_name or ''}".strip() or u.supervisor.username or '-')

            ws.append([
                u.id,
                b(u.is_active),
                nome_completo,
                u.first_name or '',
                u.last_name or '',
                u.username or '',
                u.email or '',
                u.cpf or '',
                u.matricula_pap or '',
                u.senha_pap or '',
                perfil_nome,
                lider_nome,
                u.canal or '',
                u.cluster or '',
                u.tel_whatsapp or '',
                u.tel_whatsapp_2 or '',
                u.tel_whatsapp_3 or '',
                u.brpronto_login or '',
                u.brpronto_senha or '',
                u.brpronto_dominio or '',
                u.meta_comissao if u.meta_comissao is not None else '',
                u.chave_pix or '',
                u.nome_da_conta or '',
                float(u.valor_almoco or 0),
                float(u.valor_passagem or 0),
                float(u.desconto_boleto or 0),
                float(u.desconto_inclusao_viabilidade or 0),
                float(u.desconto_instalacao_antecipada or 0),
                float(u.adiantamento_cnpj or 0),
                float(u.desconto_inss_fixo or 0),
                b(u.participa_controle_presenca),
                b(u.vendedor_solo),
                b(u.autorizar_venda_sem_auditoria),
                b(u.autorizar_venda_automatica),
                b(u.autorizar_analise_credito_wpp),
                b(u.autorizar_inclusao_wpp),
                b(u.login_pap_disponivel_para_automacao),
                b(u.pap_automacao_vender),
                b(u.pap_automacao_credito),
                b(u.pap_automacao_pedido),
                b(u.pap_automacao_status),
            ])

        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 45)

        status_label = "todos"
        is_active_param = request.query_params.get('is_active')
        if is_active_param is not None:
            status_label = "ativos" if is_active_param.lower() in ('true', '1') else "inativos"

        filename = f"usuarios_{status_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response


class GestaoAcessosGruposView(APIView):
    """Lista grupos (perfis) permitidos na Gestão de Acessos: exclui Admin e Diretoria."""
    permission_classes = [permissions.IsAuthenticated, PodeGestaoAcessos]

    def get(self, request):
        grupos = Group.objects.exclude(name__in=PERFIS_EXCLUIDOS_GESTAO_ACESSOS).order_by('name')
        serializer = GroupSerializer(grupos, many=True)
        return Response(serializer.data)

class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class GrupoViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().order_by('name')
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class PermissaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Desabilita paginação para retornar todas as permissões
    
    def get_queryset(self):
        meus_apps = ['crm_app', 'usuarios', 'presenca', 'osab', 'relatorios']
        return Permission.objects.filter(content_type__app_label__in=meus_apps).distinct().order_by('content_type__model', 'codename')
    
    def list(self, request, *args, **kwargs):
        """
        Sobrescreve o método list para garantir que todas as permissões sejam retornadas
        sem paginação, mesmo que a paginação global esteja habilitada.
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class PerfilViewSet(viewsets.ModelViewSet):
    queryset = Perfil.objects.all().order_by('nome')
    serializer_class = PerfilSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        response = super().list(request, *args, **kwargs)
        # logger.debug(f"[DEBUG PERFIS] Perfis retornados: {response.data}")
        return response

    @action(detail=True, methods=['get', 'put'], url_path='permissoes')
    def permissoes(self, request, pk=None):
        perfil = self.get_object()
        if request.method == 'GET':
            permissions = perfil.permissoes.all()
            codenames = []
            for p in permissions:
                if p.pode_ver: codenames.append(f"can_view_{p.recurso}")
                if p.pode_criar: codenames.append(f"can_add_{p.recurso}")
                if p.pode_editar: codenames.append(f"can_change_{p.recurso}")
                if p.pode_excluir: codenames.append(f"can_delete_{p.recurso}")
            return Response(codenames)
        elif request.method == 'PUT':
            permissoes_data = request.data.get('permissoes', [])
            recursos_para_atualizar = {}
            for p_data in permissoes_data:
                recurso = p_data.get('recurso')
                acao = p_data.get('acao')
                ativo = p_data.get('ativo')
                if recurso not in recursos_para_atualizar:
                    recursos_para_atualizar[recurso] = {'pode_ver': False, 'pode_criar': False, 'pode_editar': False, 'pode_excluir': False}
                if acao == 'view': recursos_para_atualizar[recurso]['pode_ver'] = ativo
                elif acao == 'add': recursos_para_atualizar[recurso]['pode_criar'] = ativo
                elif acao == 'change': recursos_para_atualizar[recurso]['pode_editar'] = ativo
                elif acao == 'delete': recursos_para_atualizar[recurso]['pode_excluir'] = ativo
            try:
                with transaction.atomic():
                    perfil.permissoes.all().delete()
                    for recurso, permissoes in recursos_para_atualizar.items():
                        if any(permissoes.values()):
                            PermissaoPerfil.objects.create(perfil=perfil, recurso=recurso, **permissoes)
            except Exception as e:
                return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return Response({'status': 'permissões atualizadas'}, status=status.HTTP_200_OK)

class UserProfileView(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    def list(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

class RecursoViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    def list(self, request):
        app_models = {
            'crm_app': ['venda', 'cliente', 'plano', 'operadora'],
            'presenca': ['presenca'],
            'usuarios': ['usuario', 'perfil']
        }
        recursos_formatados = []
        for app, models in app_models.items():
            for model in models:
                recursos_formatados.append(f"{app}_{model}")
        return Response(recursos_formatados)

class DefinirNovaSenhaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TrocaSenhaSerializer(data=request.data)
        if serializer.is_valid():
            usuario = request.user
            nova_senha = serializer.validated_data['nova_senha']
            usuario.set_password(nova_senha)
            usuario.obriga_troca_senha = False
            usuario.save()
            return Response({"detail": "Senha alterada com sucesso!"})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UsuarioPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 1000


class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all().select_related('supervisor', 'perfil').prefetch_related('groups').order_by('first_name')
    serializer_class = UsuarioSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = UsuarioPagination
    ordering_fields = ['username', 'first_name', 'last_name', 'email', 'canal', 'cluster']
    ordering = ['first_name']  # padrão para listagem da gestão

    def get_queryset(self):
        """
        Processa parâmetros da query: is_active, search, canal, perfil, cluster.
        """
        queryset = super().get_queryset()
        
        is_active_param = self.request.query_params.get('is_active')
        if is_active_param is not None:
            is_active_value = is_active_param.lower() in ('true', '1')
            queryset = queryset.filter(is_active=is_active_value)
        
        # Filtro por canal (PAP, PARCEIRO, DIGITAL, etc.)
        canal = (self.request.query_params.get('canal') or '').strip()
        if canal:
            queryset = queryset.filter(canal=canal)
        
        # Filtro por perfil (id do perfil)
        perfil_id = self.request.query_params.get('perfil')
        if perfil_id:
            try:
                queryset = queryset.filter(perfil_id=int(perfil_id))
            except (ValueError, TypeError):
                pass
        
        # Filtro por cluster (CLUSTER_1, CLUSTER_2, CLUSTER_3)
        cluster = (self.request.query_params.get('cluster') or '').strip()
        if cluster:
            queryset = queryset.filter(cluster=cluster)
        
        # Busca dinâmica: username, nome, sobrenome, e-mail (case-insensitive)
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            q = Q(username__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search)
            queryset = queryset.filter(q)

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=True, methods=['put'], url_path='reativar')
    def reativar(self, request, pk=None):
        """Reativa um usuário inativo (is_active=True)."""
        usuario = self.get_object()
        usuario.is_active = True
        usuario.save()
        return Response({'status': 'reativado'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path='excluir-definitivo')
    def excluir_definitivo(self, request, pk=None):
        """
        Exclui definitivamente o usuário e registros relacionados (FK) existentes no banco.
        Disponível apenas para superusuário.
        """
        if not request.user.is_superuser:
            return Response(
                {'detail': 'Apenas superusuário pode excluir definitivamente usuários.'},
                status=status.HTTP_403_FORBIDDEN
            )

        usuario = self.get_object()
        if usuario.id == request.user.id:
            return Response(
                {'detail': 'Não é permitido excluir o próprio usuário logado.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario_id = usuario.id
        deletados_relacionados = 0

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            tc.table_schema,
                            tc.table_name,
                            kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                        JOIN information_schema.constraint_column_usage ccu
                          ON ccu.constraint_name = tc.constraint_name
                         AND ccu.table_schema = tc.table_schema
                        WHERE tc.constraint_type = 'FOREIGN KEY'
                          AND ccu.table_name = 'usuarios_usuario'
                          AND ccu.column_name = 'id'
                        ORDER BY tc.table_schema, tc.table_name
                        """
                    )
                    referencias = cursor.fetchall()

                    for schema_name, table_name, column_name in referencias:
                        tabela = f'{connection.ops.quote_name(schema_name)}.{connection.ops.quote_name(table_name)}'
                        coluna = connection.ops.quote_name(column_name)
                        cursor.execute(f"DELETE FROM {tabela} WHERE {coluna} = %s", [usuario_id])
                        deletados_relacionados += cursor.rowcount or 0

                    # DELETE direto no SQL: evita o collector do Django, que faria SET_NULL/CASCADE em
                    # *todos* os modelos registrados — inclusive tabelas ausentes no banco (ex.: outro
                    # deploy/migration), o que gera erro mesmo após limpar FKs reais em information_schema.
                    utable = connection.ops.quote_name(Usuario._meta.db_table)
                    cursor.execute(f"DELETE FROM {utable} WHERE {connection.ops.quote_name('id')} = %s", [usuario_id])

        except Exception as exc:
            return Response(
                {'detail': f'Erro ao excluir definitivamente: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                'status': 'excluido_definitivamente',
                'usuario_id': usuario_id,
                'registros_relacionados_removidos': deletados_relacionados,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def lideres(self, request):
        usuarios = Usuario.objects.filter(is_active=True).values('id', 'username', 'first_name', 'last_name')
        data = []
        for u in usuarios:
            nome = f"{u['first_name']} {u['last_name']}".strip()
            if not nome:
                nome = u['username']
            else:
                nome = f"{nome} ({u['username']})"
            data.append({
                'id': u['id'], 
                'username': u['username'],
                'nome_exibicao': nome
            })
        return Response(data)

    @action(detail=False, methods=['get'], url_path='ativos-para-select')
    def ativos_para_select(self, request):
        """
        Retorna todos os usuários ativos (id, username) ordenados por username, sem paginação.
        Uso: dropdowns de Novo Adiantamento e Novo Desconto.
        """
        qs = Usuario.objects.filter(is_active=True).order_by('username').values('id', 'username', 'recebe_adiantamento_cnpj')
        return Response(list(qs))

    @action(detail=False, methods=['post'])
    def trocar_senha(self, request):
        serializer = TrocaSenhaSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            user.set_password(serializer.validated_data['nova_senha'])
            user.obriga_troca_senha = False
            user.save()
            return Response({'status': 'senha alterada'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def solicitar_reset_senha(self, request):
        serializer = ResetSenhaSolicitacaoSerializer(data=request.data)
        if serializer.is_valid():
            return Response({'mensagem': 'Solicitação recebida.'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Retorna dados do usuário atual"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='exportar-excel')
    def exportar_excel(self, request):
        """
        Exporta usuários para Excel respeitando os filtros da listagem:
        is_active, search, canal, perfil e cluster.
        """
        queryset = self.filter_queryset(self.get_queryset()).order_by('first_name', 'username')

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Usuarios"

        headers = [
            "ID",
            "Ativo",
            "Nome completo",
            "Primeiro nome",
            "Sobrenome",
            "Username",
            "Email",
            "CPF",
            "Matricula PAP",
            "Senha PAP",
            "Perfil",
            "Lider",
            "Canal",
            "Cluster",
            "WhatsApp 1",
            "WhatsApp 2",
            "WhatsApp 3",
            "Br Pronto Login",
            "Br Pronto Senha",
            "Br Pronto Dominio",
            "Meta comissao",
            "Chave PIX",
            "Nome da conta",
            "Valor almoco",
            "Valor passagem",
            "Desconto boleto",
            "Desconto inclusao viabilidade",
            "Desconto instalacao antecipada",
            "Adiantamento CNPJ",
            "Desconto INSS fixo",
            "Participa controle presenca",
            "Vendedor solo",
            "Autorizar venda sem auditoria",
            "Autorizar venda automatica",
            "Autorizar analise credito WPP",
            "Autorizar inclusao WPP",
            "Login PAP disponivel automacao",
            "PAP automacao vender",
            "PAP automacao credito",
            "PAP automacao pedido",
            "PAP automacao status",
        ]
        ws.append(headers)

        def b(value):
            return "Sim" if bool(value) else "Nao"

        for u in queryset:
            nome_completo = f"{u.first_name or ''} {u.last_name or ''}".strip() or u.username
            perfil_nome = getattr(u.perfil, 'nome', '') or '-'
            lider_nome = '-'
            if u.supervisor:
                lider_nome = (f"{u.supervisor.first_name or ''} {u.supervisor.last_name or ''}".strip() or u.supervisor.username or '-')

            ws.append([
                u.id,
                b(u.is_active),
                nome_completo,
                u.first_name or '',
                u.last_name or '',
                u.username or '',
                u.email or '',
                u.cpf or '',
                u.matricula_pap or '',
                u.senha_pap or '',
                perfil_nome,
                lider_nome,
                u.canal or '',
                u.cluster or '',
                u.tel_whatsapp or '',
                u.tel_whatsapp_2 or '',
                u.tel_whatsapp_3 or '',
                u.brpronto_login or '',
                u.brpronto_senha or '',
                u.brpronto_dominio or '',
                u.meta_comissao if u.meta_comissao is not None else '',
                u.chave_pix or '',
                u.nome_da_conta or '',
                float(u.valor_almoco or 0),
                float(u.valor_passagem or 0),
                float(u.desconto_boleto or 0),
                float(u.desconto_inclusao_viabilidade or 0),
                float(u.desconto_instalacao_antecipada or 0),
                float(u.adiantamento_cnpj or 0),
                float(u.desconto_inss_fixo or 0),
                b(u.participa_controle_presenca),
                b(u.vendedor_solo),
                b(u.autorizar_venda_sem_auditoria),
                b(u.autorizar_venda_automatica),
                b(u.autorizar_analise_credito_wpp),
                b(u.autorizar_inclusao_wpp),
                b(u.login_pap_disponivel_para_automacao),
                b(u.pap_automacao_vender),
                b(u.pap_automacao_credito),
                b(u.pap_automacao_pedido),
                b(u.pap_automacao_status),
            ])

        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 45)

        status_label = "todos"
        is_active_param = request.query_params.get('is_active')
        if is_active_param is not None:
            status_label = "ativos" if is_active_param.lower() in ('true', '1') else "inativos"

        filename = f"usuarios_governanca_{status_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response
    
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated], url_path='definir-senha')
    def definir_nova_senha(self, request):
        serializer = TrocaSenhaSerializer(data=request.data)
        if serializer.is_valid():
            usuario = request.user
            nova_senha = serializer.validated_data['nova_senha']
            
            usuario.set_password(nova_senha)
            usuario.obriga_troca_senha = False
            usuario.save()
            
            # Retorna novo token para o frontend atualizar e parar de pedir troca
            refresh = RefreshToken.for_user(usuario)
            return Response({
                "detail": "Senha alterada com sucesso!",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "obriga_troca_senha": False,
            })
        
        return Response(serializer.errors, status=400)

    # --- NOVO ENDPOINT DE VALIDAÇÃO ASSÍNCRONA ---
    @action(detail=False, methods=['post'], url_path='validar-whatsapp')
    def validar_whatsapp(self, request):
        """
        Endpoint leve para verificar WhatsApp sem travar o banco ou a interface.
        Uso: POST /api/usuarios/validar-whatsapp/ { "telefone": "31999999999" }
        """
        telefone = request.data.get('telefone')
        
        # 1. Limpeza básica
        telefone_limpo = "".join(filter(str.isdigit, str(telefone or "")))
        
        if len(telefone_limpo) < 10 or len(telefone_limpo) > 13:
             return Response({
                 "valido": False, 
                 "mensagem": "Formato inválido. Digite DDD + Número (ex: 31999999999)."
             }, status=200)

        # 2. Normalizar celular BR: 10 dígitos (DDD+8, ex: 3188804000 MG) -> 11 (DDD+9+8)
        if len(telefone_limpo) == 10 and telefone_limpo[2:3] != "9":
            telefone_limpo = telefone_limpo[:2] + "9" + telefone_limpo[2:]

        # 3. Validação na API do WhatsApp (Z-API)
        try:
            service = WhatsAppService()
            if not service.token or not service.instance_id:
                return Response({
                    "valido": True,
                    "aviso": "API WhatsApp não configurada no servidor. Validação ignorada."
                }, status=200)

            if len(telefone_limpo) <= 11:
                telefone_api = f"55{telefone_limpo}"
            else:
                telefone_api = telefone_limpo

            existe = service.verificar_numero_existe(telefone_api)

            if existe is None:
                # API retornou erro (timeout, etc.) – não bloquear cadastro
                return Response({
                    "valido": True,
                    "aviso": "Não foi possível validar. Pode salvar."
                }, status=200)
            if existe:
                return Response({
                    "valido": True,
                    "mensagem": "WhatsApp confirmado!"
                })
            return Response({
                "valido": False,
                "mensagem": "Número não possui WhatsApp ativo."
            })

        except Exception as e:
            return Response({
                "valido": True,
                "aviso": "Não foi possível validar. Pode salvar."
            }, status=200)