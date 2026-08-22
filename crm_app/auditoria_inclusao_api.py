"""API: demandas de Inclusão/Viabilidade na Auditoria (+ payload para extensão Chrome)."""
from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .auditoria_sem_slot_utils import PERFIS_AUDITORIA
from .models import DemandaInclusaoViabilidade
from .utils import is_member

logger = logging.getLogger(__name__)


def _exige_auditoria(user) -> Response | None:
    if not is_member(user, PERFIS_AUDITORIA):
        return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _nome_usuario(user) -> str:
    if not user:
        return ""
    full = ""
    try:
        full = (user.get_full_name() or "").strip()
    except Exception:
        full = ""
    if full:
        return full
    for attr in ("nome", "first_name", "username", "email"):
        val = getattr(user, attr, None)
        if val:
            return str(val)
    return str(user.pk)


def _serialize_demanda(d: DemandaInclusaoViabilidade, *, detalhe: bool = False) -> dict:
    viacep = (d.dados or {}).get("viacep") or {}
    base = {
        "id": d.id,
        "protocolo": d.protocolo,
        "status": d.status,
        "telefone_solicitante": d.telefone_solicitante,
        "solicitante_nome": _nome_usuario(d.solicitante),
        "auditor_nome": _nome_usuario(d.auditor),
        "cidade": viacep.get("localidade") or "",
        "uf": viacep.get("uf") or "",
        "cep": (d.dados or {}).get("cep") or "",
        "logradouro": viacep.get("logradouro") or "",
        "numero": (d.dados or {}).get("numero_fachada") or "",
        "qtd_arquivos": len(d.arquivos_urls or []),
        "criado_em": d.criado_em.isoformat() if d.criado_em else None,
        "enviado_em": d.enviado_em.isoformat() if d.enviado_em else None,
        "erro_mensagem": d.erro_mensagem or "",
    }
    if detalhe:
        base["dados"] = d.dados or {}
        base["form_payload"] = d.form_payload or {}
        base["arquivos_urls"] = d.arquivos_urls or []
        base["r2_folder"] = d.r2_folder or ""
        base["observacoes"] = d.observacoes or ""
    return base


class DemandaInclusaoListView(APIView):
    """GET lista demandas de inclusão (padrão: pendentes + em andamento)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        neg = _exige_auditoria(request.user)
        if neg:
            return neg

        status_filtro = (request.query_params.get("status") or "").strip().upper()
        qs = DemandaInclusaoViabilidade.objects.select_related("solicitante", "auditor")
        if status_filtro == "TODAS":
            pass
        elif status_filtro:
            qs = qs.filter(status=status_filtro)
        else:
            qs = qs.filter(
                status__in=[
                    DemandaInclusaoViabilidade.STATUS_PENDENTE,
                    DemandaInclusaoViabilidade.STATUS_EM_ANDAMENTO,
                ]
            )

        limit = min(int(request.query_params.get("page_size") or 100), 200)
        itens = [_serialize_demanda(d) for d in qs[:limit]]
        return Response({"count": len(itens), "results": itens})


class DemandaInclusaoDetailView(APIView):
    """GET detalhe + form_payload para a extensão Chrome."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int):
        neg = _exige_auditoria(request.user)
        if neg:
            return neg
        try:
            d = DemandaInclusaoViabilidade.objects.select_related(
                "solicitante", "auditor"
            ).get(pk=pk)
        except DemandaInclusaoViabilidade.DoesNotExist:
            return Response({"detail": "Demanda não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_demanda(d, detalhe=True))


class DemandaInclusaoIniciarView(APIView):
    """POST: auditor assume a demanda (status EM_ANDAMENTO)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        neg = _exige_auditoria(request.user)
        if neg:
            return neg
        try:
            d = DemandaInclusaoViabilidade.objects.get(pk=pk)
        except DemandaInclusaoViabilidade.DoesNotExist:
            return Response({"detail": "Demanda não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        if d.status == DemandaInclusaoViabilidade.STATUS_ENVIADA:
            return Response(
                {"detail": "Demanda já foi enviada ao Forms.", "demanda": _serialize_demanda(d, detalhe=True)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if d.status == DemandaInclusaoViabilidade.STATUS_CANCELADA:
            return Response({"detail": "Demanda cancelada."}, status=status.HTTP_400_BAD_REQUEST)

        d.status = DemandaInclusaoViabilidade.STATUS_EM_ANDAMENTO
        d.auditor = request.user
        d.erro_mensagem = ""
        d.save(update_fields=["status", "auditor", "erro_mensagem", "atualizado_em"])
        return Response(
            {
                "success": True,
                "demanda": _serialize_demanda(d, detalhe=True),
                "form_payload": d.form_payload or {},
            }
        )


class DemandaInclusaoConcluirView(APIView):
    """POST: marca demanda como ENVIADA após sucesso da extensão."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        neg = _exige_auditoria(request.user)
        if neg:
            return neg
        try:
            d = DemandaInclusaoViabilidade.objects.get(pk=pk)
        except DemandaInclusaoViabilidade.DoesNotExist:
            return Response({"detail": "Demanda não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        d.status = DemandaInclusaoViabilidade.STATUS_ENVIADA
        d.auditor = request.user
        d.enviado_em = timezone.now()
        d.erro_mensagem = ""
        d.save(
            update_fields=["status", "auditor", "enviado_em", "erro_mensagem", "atualizado_em"]
        )
        logger.info("[Inclusão] Demanda #%s marcada ENVIADA por user=%s", d.id, request.user_id)
        return Response({"success": True, "demanda": _serialize_demanda(d)})


class DemandaInclusaoErroView(APIView):
    """POST: registra falha no preenchimento local."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        neg = _exige_auditoria(request.user)
        if neg:
            return neg
        try:
            d = DemandaInclusaoViabilidade.objects.get(pk=pk)
        except DemandaInclusaoViabilidade.DoesNotExist:
            return Response({"detail": "Demanda não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        msg = (request.data.get("mensagem") or request.data.get("erro") or "").strip()
        d.status = DemandaInclusaoViabilidade.STATUS_ERRO
        d.auditor = request.user
        d.erro_mensagem = msg[:2000]
        d.save(update_fields=["status", "auditor", "erro_mensagem", "atualizado_em"])
        return Response({"success": True, "demanda": _serialize_demanda(d)})
