# crm_app/historico_pap_api.py
"""API do Funil: buscar histórico PAP (venda / interesse / pré-venda)."""
from __future__ import annotations

import base64
import logging
from datetime import date, datetime

from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.historico_pap import MAX_DIAS_BUSCA, tipos_solicitados
from crm_app.legado_pap_osab import validar_upload
from crm_app.utils import is_member

logger = logging.getLogger(__name__)


def _parse_date(valor, fallback: date) -> date:
    raw = (valor or "").strip()
    if not raw:
        return fallback
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return fallback


class FunilHistoricoPapConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        from crm_app.historico_pap_service import busca_em_andamento, serializar_busca
        from crm_app.models import HistoricoPapBusca, HistoricoPapPedido
        from crm_app.pool_historico_pap import resumo_pool

        hoje = date.today()
        busca = busca_em_andamento()
        ultima = HistoricoPapBusca.objects.select_related("login_pap").order_by("-iniciado_em").first()
        pool = resumo_pool()
        return Response(
            {
                "tipos": ["VENDA", "INTERESSE", "PRE_VENDA"],
                "data_inicio": date(hoje.year, hoje.month, 1).isoformat(),
                "data_fim": hoje.isoformat(),
                "max_dias": MAX_DIAS_BUSCA,
                "tem_credencial_pap": pool["disponiveis"] > 0 or pool["em_uso"] > 0,
                "pool": pool,
                "pedidos_conhecidos": HistoricoPapPedido.objects.count(),
                "grava_venda": False,
                "busca_em_andamento": serializar_busca(busca, em_andamento=True) if busca else None,
                "ultima_busca": serializar_busca(ultima, em_andamento=False) if ultima and not busca else (
                    serializar_busca(ultima, em_andamento=False) if ultima else None
                ),
            }
        )


class FunilHistoricoPapRegistrarView(APIView):
    """Marca protocolos da exportação (coluna Pedido) para não buscar de novo."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        arq = request.FILES.get("arquivo") or request.FILES.get("pap") or request.FILES.get("exportacao")
        if not arq:
            return Response({"error": "Envie a exportação PAP no campo 'arquivo'."}, status=400)
        try:
            nome = arq.name or ""
            if nome.lower().endswith(".json"):
                if (arq.size or 0) > 25 * 1024 * 1024:
                    return Response({"error": "Arquivo maior que 25 MB."}, status=400)
            else:
                validar_upload(nome, arq.size or 0)
            from crm_app.historico_pap_service import registrar_exportacao

            resumo = registrar_exportacao(request.user, nome, arq.read())
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("Falha ao registrar exportação PAP")
            return Response({"error": "Não foi possível ler o arquivo."}, status=400)
        return Response({"success": True, **resumo})


class FunilHistoricoPapBuscarView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        hoje = date.today()
        data = request.data if isinstance(request.data, dict) else {}
        data_inicio = _parse_date(data.get("data_inicio"), date(hoje.year, hoje.month, 1))
        data_fim = _parse_date(data.get("data_fim"), hoje)
        tipos_raw = data.get("tipos") or []
        if isinstance(tipos_raw, str):
            tipos_raw = [p.strip() for p in tipos_raw.split(",") if p.strip()]
        tipos = tipos_solicitados(tipos_raw)

        from crm_app.historico_pap_service import criar_e_iniciar_busca

        exec_id, err = criar_e_iniciar_busca(
            request.user,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pdv="",
            tipos=tipos,
        )
        if err:
            low = err.lower()
            code = 409 if ("em uso" in low or "andamento" in low) else 400
            return Response({"error": err}, status=code)
        return Response(
            {
                "success": True,
                "busca_id": exec_id,
                "status": "em_andamento",
                "grava_venda": False,
                "tipos": tipos,
            },
            status=202,
        )


class FunilHistoricoPapStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        from crm_app.historico_pap_service import busca_em_andamento, serializar_busca
        from crm_app.models import HistoricoPapBusca

        busca_id = request.query_params.get("id") or request.query_params.get("busca_id")
        if busca_id:
            busca = HistoricoPapBusca.objects.filter(pk=busca_id).select_related("login_pap").first()
            if not busca:
                return Response({"error": "Busca não encontrada."}, status=404)
            em = busca.status in (
                HistoricoPapBusca.STATUS_PENDENTE,
                HistoricoPapBusca.STATUS_EM_ANDAMENTO,
            )
            return Response(serializar_busca(busca, em_andamento=em))

        atual = busca_em_andamento()
        if atual:
            return Response(serializar_busca(atual, em_andamento=True))
        ultima = HistoricoPapBusca.objects.select_related("login_pap").order_by("-iniciado_em").first()
        if not ultima:
            return Response({"em_andamento": False, "ultima": None})
        return Response({"em_andamento": False, "ultima": serializar_busca(ultima, em_andamento=False)})


class FunilHistoricoPapDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        from crm_app.historico_pap_service import xlsx_novos_da_busca
        from crm_app.models import HistoricoPapBusca

        busca_id = request.query_params.get("id") or request.query_params.get("busca_id")
        if busca_id:
            busca = HistoricoPapBusca.objects.filter(pk=busca_id).first()
        else:
            busca = HistoricoPapBusca.objects.filter(status=HistoricoPapBusca.STATUS_CONCLUIDO).order_by("-iniciado_em").first()
        if not busca:
            return Response({"error": "Nenhuma busca concluída para baixar."}, status=404)
        try:
            blob, nome = xlsx_novos_da_busca(busca.id)
        except Exception:
            logger.exception("Falha ao montar Excel do histórico PAP")
            return Response({"error": "Não foi possível montar a planilha."}, status=400)
        return Response(
            {
                "success": True,
                "nome_arquivo": nome,
                "novos": busca.novos,
                "arquivo_base64": base64.b64encode(blob).decode("ascii"),
                "grava_venda": False,
            }
        )
