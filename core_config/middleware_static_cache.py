"""
Cache-Control longo para arquivos estáticos — reduz carga no Gunicorn quando saturado.
"""
from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class StaticCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.max_age = int(getattr(settings, "STATIC_CACHE_MAX_AGE", 86400))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if (
            request.path.startswith("/static/")
            and response.status_code == 200
            and "Cache-Control" not in response
        ):
            response["Cache-Control"] = f"public, max-age={self.max_age}, immutable"
        return response
