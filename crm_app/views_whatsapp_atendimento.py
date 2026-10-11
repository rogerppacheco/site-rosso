"""Página e API do inbox de atendimento WhatsApp (número do cliente)."""
from __future__ import annotations

from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.services.whatsapp.atendimento_service import (
    assumir_conversa,
    detalhe_conversa,
    listar_conversas,
    responder_texto,
)
from crm_app.utils import is_member

GRUPOS_ATENDIMENTO = ("Diretoria", "Admin", "BackOffice", "Auditoria", "Qualidade")


def page_atendimento_whatsapp(request):
    """Tela de conversas do WhatsApp oficial."""
    return render(request, "atendimento-whatsapp.html")


class _AtendimentoAutenticado(APIView):
    permission_classes = [IsAuthenticated]

    def _negar_se_sem_perfil(self, request):
        if is_member(request.user, list(GRUPOS_ATENDIMENTO)):
            return None
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)


class AtendimentoWhatsAppConversasView(_AtendimentoAutenticado):
    """GET: lista de conversas do número oficial."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        busca = request.query_params.get("q") or ""
        return Response({"items": listar_conversas(request.user, busca)})


class AtendimentoWhatsAppDetalheView(_AtendimentoAutenticado):
    """GET: histórico completo de um telefone."""

    def get(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        detalhe = detalhe_conversa(request.user, telefone)
        if detalhe is None:
            return Response({"detail": "Conversa não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response(detalhe)


class AtendimentoWhatsAppResponderView(_AtendimentoAutenticado):
    """POST: texto livre, somente com a janela de 24 horas aberta."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        texto = request.data.get("texto") if isinstance(request.data, dict) else ""
        codigo, payload = responder_texto(request.user, telefone, texto or "")
        if codigo == "ok":
            return Response(payload)
        if codigo == "janela_fechada":
            return Response(payload, status=status.HTTP_409_CONFLICT)
        if codigo == "canal_indisponivel":
            return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if codigo == "falha_envio":
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        if codigo == "nao_encontrado":
            return Response(payload, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class AtendimentoWhatsAppAssumirView(_AtendimentoAutenticado):
    """POST: pausa o bot neste telefone sem enviar mensagem."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        detalhe = assumir_conversa(request.user, telefone)
        if detalhe is None:
            return Response({"detail": "Conversa não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True, "bot_pausado": True, "conversa": detalhe})
