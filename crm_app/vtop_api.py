"""
API REST para automação SmartRiser (V.top) acionada pelo Gestão CDOI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import CdoiSolicitacao
from crm_app.services_vtop_smartriser import (
    get_vtop_service,
    montar_payload_cdoi,
    payload_para_bloco,
)
from crm_app.utils import is_member

logger = logging.getLogger(__name__)


def _pode_usar_vtop(user) -> bool:
    return is_member(user, ["Diretoria", "Admin", "BackOffice"])


def _carregar_cdoi(pk: int) -> Optional[CdoiSolicitacao]:
    try:
        return CdoiSolicitacao.objects.prefetch_related("blocos").get(pk=pk)
    except CdoiSolicitacao.DoesNotExist:
        return None


def _payload_com_overrides(cdoi: CdoiSolicitacao, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = montar_payload_cdoi(cdoi)
    # Overrides opcionais (campos ainda sem fonte no CDOI)
    for chave in ("cod_survey", "estacao", "celula", "cdoi_codigo", "complemento", "codigo_sap"):
        if chave in data and data.get(chave) is not None:
            payload[chave] = str(data.get(chave)).strip()
    return payload


class CdoiVtopStatusView(APIView):
    """GET — status da automação / sessão persistida."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        if not _pode_usar_vtop(request.user):
            return Response({"error": "Acesso negado."}, status=403)
        svc = get_vtop_service()
        state = svc.get_state()
        return Response({"ok": True, "state": state})


class CdoiVtopIniciarView(APIView):
    """
    POST — inicia automação para o CDOI (1 bloco = 1 obra).

    Fluxo padrão:
      1. Inventário Brownfield no endereço (logradouro+número)
      2. Se já existir o mesmo complemento → reabre essa obra (não duplica)
      3. Senão → cria obra nova → Cadastro → salvar → validar

    Body JSON opcional:
      forcar_login: bool
      pausar_apos / somente_ate: str
      bloco / nome_bloco: str (obrigatório para obra)
      obra_id + forcar_obra_id: reabre direto sem inventário
      permitir_criar: false — bloqueia criação nesta requisição
      vtop_usuario / vtop_senha — credenciais do modal (só memória desta execução)
      cod_survey, estacao, celula, complemento, codigo_sap — overrides
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        if not _pode_usar_vtop(request.user):
            return Response({"error": "Acesso negado."}, status=403)

        cdoi = _carregar_cdoi(pk)
        if not cdoi:
            return Response({"error": "CDOI não encontrado."}, status=404)

        data = request.data if isinstance(request.data, dict) else {}
        payload = _payload_com_overrides(cdoi, data)
        somente_ate = (data.get("somente_ate") or "").strip().lower() or None

        bloco = (data.get("bloco") or data.get("nome_bloco") or "").strip()
        if bloco:
            try:
                payload = payload_para_bloco(payload, bloco)
            except ValueError as exc:
                return Response({"error": str(exc)}, status=400)
        elif somente_ate not in ("login", None) and somente_ate != "login":
            if somente_ate and somente_ate != "login" and not payload.get("complemento"):
                return Response(
                    {
                        "error": "Informe o bloco (ex.: BLOCO 05). Cada bloco vira uma obra separada.",
                        "blocos": [b.get("nome") for b in (payload.get("blocos") or [])],
                    },
                    status=400,
                )

        # forcar_obra_id: atalho sem inventário
        if data.get("obra_id"):
            payload["obra_id"] = str(data.get("obra_id")).strip()
        if data.get("forcar_obra_id") or data.get("forcarObraId"):
            payload["forcar_obra_id"] = True
        if "permitir_criar" in data or "permitirCriar" in data:
            payload["permitir_criar"] = bool(
                data.get("permitir_criar", data.get("permitirCriar"))
            )
        # Credenciais do modal (só memória desta execução — não logar / não persistir)
        usuario = (data.get("vtop_usuario") or data.get("usuario") or "").strip()
        senha = data.get("vtop_senha") or data.get("senha") or ""
        if usuario:
            payload["vtop_usuario"] = usuario
        if senha:
            payload["vtop_senha"] = str(senha)

        faltando = []
        if somente_ate != "login":
            if not payload.get("nome_condominio"):
                faltando.append("nome_condominio")
            if not payload.get("logradouro"):
                faltando.append("logradouro")
            if not payload.get("uf"):
                faltando.append("uf")
            if bloco and not payload.get("complemento"):
                faltando.append("bloco")
        if faltando:
            return Response(
                {"error": "Dados incompletos no CDOI.", "faltando": faltando},
                status=400,
            )

        # Não espelhar senha no state da API
        svc = get_vtop_service()
        result = svc.iniciar(
            cdoi_id=pk,
            payload=payload,
            forcar_login=bool(data.get("forcar_login")),
            pausar_apos=data.get("pausar_apos") or None,
            somente_ate=somente_ate,
        )
        # Remove vestígios da senha da resposta/extras se houver
        if isinstance(result.get("state"), dict):
            result["state"].get("extras", {}).pop("vtop_senha", None)
        code = status.HTTP_200_OK if result.get("ok") else status.HTTP_409_CONFLICT
        return Response(result, status=code)


class CdoiVtopSenhaProntaView(APIView):
    """POST — sinaliza que o usuário já digitou login/senha no browser."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        if not _pode_usar_vtop(request.user):
            return Response({"error": "Acesso negado."}, status=403)
        svc = get_vtop_service()
        # pk só valida existência / contexto da UI
        if not _carregar_cdoi(pk):
            return Response({"error": "CDOI não encontrado."}, status=404)
        result = svc.signal_senha_pronta()
        code = status.HTTP_200_OK if result.get("ok") else status.HTTP_409_CONFLICT
        return Response(result, status=code)


class CdoiVtopFecharView(APIView):
    """POST — fecha o browser preservando a sessão (não desloga do IdP)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        if not _pode_usar_vtop(request.user):
            return Response({"error": "Acesso negado."}, status=403)
        data = request.data if isinstance(request.data, dict) else {}
        manter = data.get("manter_sessao", True)
        if isinstance(manter, str):
            manter = manter.lower() not in ("false", "0", "no")
        result = get_vtop_service().fechar_navegador(manter_sessao=bool(manter))
        return Response(result)


class CdoiVtopInvalidarSessaoView(APIView):
    """POST — apaga storage_state. Use só se a sessão estiver inválida."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _pode_usar_vtop(request.user):
            return Response({"error": "Acesso negado."}, status=403)
        result = get_vtop_service().invalidar_sessao()
        return Response(result)


class CdoiVtopPayloadPreviewView(APIView):
    """GET — mostra o mapeamento CDOI→V.top sem abrir o browser (útil para validar dados)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int):
        if not _pode_usar_vtop(request.user):
            return Response({"error": "Acesso negado."}, status=403)
        cdoi = _carregar_cdoi(pk)
        if not cdoi:
            return Response({"error": "CDOI não encontrado."}, status=404)
        payload = montar_payload_cdoi(cdoi)
        # Não expor URLs assinadas longas na íntegra se preferir — aqui reduzimos querystring
        for k in ("link_carta", "link_fachada"):
            if payload.get(k):
                payload[k + "_presente"] = True
                payload[k] = (payload[k][:80] + "…") if len(payload[k]) > 80 else payload[k]
        return Response({"ok": True, "payload": payload})
