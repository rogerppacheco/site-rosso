# site-record/usuarios/permissions.py

from rest_framework import permissions

from crm_app.perfis_acesso import is_somente_leitura

class CheckAPIPermission(permissions.BasePermission):
    """
    Verifica as permissões do usuário usando o sistema nativo do Django (Grupos e Permissions).
    
    Mantém a compatibilidade com a lógica antiga de 'resource_name' definida nas Views.
    Exemplo na View:
        class VendaViewSet(viewsets.ModelViewSet):
            permission_classes = [CheckAPIPermission]
            resource_name = 'venda'  # Nome do model (ex: 'venda', 'cliente')
    """
    def has_permission(self, request, view):
        # 1. Verifica se o usuário está logado
        if not request.user or not request.user.is_authenticated:
            return False

        # 2. Superusuário sempre tem acesso total
        if request.user.is_superuser:
            return True

        # 3. Identifica o recurso (Model) que a View está acessando
        resource_name = getattr(view, 'resource_name', None)
        
        # Se a view não definir 'resource_name', tentamos inferir ou permitimos se for IsAuthenticated
        # Para segurança estrita, se não tiver resource_name, usamos a VendaPermission ou bloqueamos.
        if not resource_name:
            return True

        # 4. Mapeia o método HTTP para a ação do Django (view, add, change, delete)
        method_map = {
            'GET': 'view',
            'OPTIONS': 'view',
            'HEAD': 'view',
            'POST': 'add',
            'PUT': 'change',
            'PATCH': 'change',
            'DELETE': 'delete',
        }
        
        action = method_map.get(request.method)
        if not action:
            return False

        # 5. Constrói o codename da permissão (ex: 'crm_app.view_venda')
        app_label = getattr(view, 'resource_app', 'crm_app') 
        permission_codename = f'{app_label}.{action}_{resource_name}'

        # 6. Verifica se o usuário tem essa permissão (via Grupo ou direta)
        return request.user.has_perm(permission_codename)


class VendaPermission(permissions.BasePermission):
    """
    Permissão específica para Vendas.
    Regra:
    1. CREATE: Qualquer autenticado pode criar.
    2. READ: Qualquer autenticado pode ler (o filtro é feito no Queryset da View).
    3. UPDATE: 
       - O dono da venda (vendedor) pode editar.
       - Quem tem permissão 'change_venda' (Backoffice/Gerente) pode editar.
       - Quem tem acesso à 'auditoria' ou 'esteira' pode editar (para mudar status).
    """
    def has_permission(self, request, view):
        # Permite acesso geral à API se estiver logado
        if not request.user.is_authenticated:
            return False
        return True

    def has_object_permission(self, request, view, obj):
        # 1. Superusers e Admins Totais (incluindo BackOffice)
        if request.user.is_superuser or request.user.groups.filter(name__in=['Diretoria', 'Admin', 'BackOffice']).exists():
            return True

        # 2. Métodos de Leitura (GET, HEAD, OPTIONS) são permitidos
        # (A segurança de quem vê o quê é feita no filtro da View, não aqui)
        if request.method in permissions.SAFE_METHODS:
            return True

        # 3. Métodos de Escrita (PUT, PATCH - Edição)
        if request.method in ['PUT', 'PATCH']:
            if is_somente_leitura(request.user):
                return False

            # A) O Vendedor dono da venda pode editar
            if obj.vendedor == request.user:
                return True
            
            # B) CORREÇÃO: Se o usuário tiver a permissão nativa de editar venda, permite.
            # Isso libera o Backoffice que tem 'crm_app.change_venda'
            if request.user.has_perm('crm_app.change_venda'):
                return True
                
            # C) CORREÇÃO EXTRA: Se o usuário tem acesso aos painéis de gestão, 
            # subentende-se que ele precisa alterar status.
            user_perms = request.user.get_all_permissions()
            if 'crm_app.can_view_auditoria' in user_perms or 'crm_app.can_view_esteira' in user_perms:
                 return True

        # 4. DELETE (Geralmente restrito)
        if request.method == 'DELETE':
            if request.user.has_perm('crm_app.delete_venda'):
                return True

        return False