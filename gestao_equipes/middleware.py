"""
Middleware customizado para desabilitar CSRF em APIs autenticadas por token JWT
"""
from django.utils.decorators import decorator_from_middleware
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework_simplejwt.authentication import JWTAuthentication


class DisableCsrfForJWT(CsrfViewMiddleware):
    """
    Desabilita CSRF para requisições com autenticação JWT.
    Permite que APIs REST com token Bearer funcionem sem CSRF token.
    """
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Se a requisição tem um header Authorization com Bearer token, skip CSRF
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if auth_header.startswith('Bearer '):
            # Marca a view como CSRF-exempt para requisições com JWT
            request.csrf_processing_done = True
            return None
        
        # Para outras requisições, aplica o CSRF normal
        return super().process_view(request, view_func, view_args, view_kwargs)
