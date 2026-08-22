from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UsuarioViewSet,
    GrupoViewSet,
    PermissaoViewSet,
    PerfilViewSet,
    RecursoViewSet,
    LoginView,
    UserProfileView,
    DefinirNovaSenhaView,
    GestaoAcessosUsuarioViewSet,
    GestaoAcessosGruposView,
)

router = DefaultRouter()
# Rotas principais (CRUDs)
router.register(r'usuarios', UsuarioViewSet, basename='usuario')
router.register(r'gestao-acessos/usuarios', GestaoAcessosUsuarioViewSet, basename='gestao-acessos-usuario')
router.register(r'grupos', GrupoViewSet, basename='grupo')
router.register(r'permissoes', PermissaoViewSet, basename='permissao')
router.register(r'perfis', PerfilViewSet, basename='perfil')
router.register(r'recursos', RecursoViewSet, basename='recurso')

# Rota auxiliar para o Frontend carregar dados do usuário logado (GET /api/usuarios/me/)
router.register(r'me', UserProfileView, basename='me')

urlpatterns = [
    # Autenticação (JWT)
    path('auth/login/', LoginView.as_view(), name='auth_login'),
    
    # Segurança
    path('auth/definir-senha/', DefinirNovaSenhaView.as_view(), name='definir_nova_senha'),
    
    # Gestão de Acessos (ferramenta delegada): grupos permitidos (sem Admin/Diretoria)
    path('gestao-acessos/grupos/', GestaoAcessosGruposView.as_view(), name='gestao-acessos-grupos'),
    
    # Rotas do Router (ViewSets)
    path('', include(router.urls)),
]