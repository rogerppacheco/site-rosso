"""Consulta do aviso de MFA do PAP para quem está logado no CRM."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .pap_mfa_aviso import listar_avisos_mfa, usuario_ve_aviso_mfa


@login_required
@require_GET
def pap_mfa_pendente_view(request):
    if not usuario_ve_aviso_mfa(request.user):
        return JsonResponse({"pendentes": []})
    return JsonResponse({"pendentes": listar_avisos_mfa()})
