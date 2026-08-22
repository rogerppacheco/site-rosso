# crm_app/funil_venda_wpp_api.py
"""API do Funil de Vendas (WhatsApp VENDER). Acesso: Diretoria e Admin."""
from django.core.paginator import Paginator
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import FunilVendaWppTentativa
from crm_app.utils import is_member


class FunilVendaWppTentativaListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        qs = FunilVendaWppTentativa.objects.select_related("usuario", "sessao_whatsapp").order_by(
            "-iniciado_em"
        )
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        telefone = (request.query_params.get("telefone") or "").strip()
        if telefone:
            qs = qs.filter(telefone__icontains=telefone)
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(max(1, int(request.query_params.get("page_size", 30))), 100)
        paginator = Paginator(qs, page_size)
        p = paginator.get_page(page)
        data = []
        for t in p.object_list:
            data.append(
                {
                    "id": t.id,
                    "telefone": t.telefone,
                    "usuario_nome": t.usuario.get_full_name() if t.usuario else None,
                    "usuario_username": t.usuario.username if t.usuario else None,
                    "matricula_pap_snapshot": t.matricula_pap_snapshot,
                    "bo_usuario_id": t.bo_usuario_id,
                    "status": t.status,
                    "funil_estagio_max": t.funil_estagio_max,
                    "etapa_codigo_atual": t.etapa_codigo_atual,
                    "protocolo_pap": t.protocolo_pap,
                    "credito_resultado": (t.credito_resultado or "")[:200],
                    "iniciado_em": t.iniciado_em.isoformat() if t.iniciado_em else None,
                    "finalizado_em": t.finalizado_em.isoformat() if t.finalizado_em else None,
                    "mensagem_erro": (t.mensagem_erro or "")[:500],
                }
            )
        return Response(
            {
                "count": paginator.count,
                "page": p.number,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
                "results": data,
            }
        )


class FunilVendaWppTentativaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        try:
            t = FunilVendaWppTentativa.objects.select_related("usuario").get(pk=pk)
        except FunilVendaWppTentativa.DoesNotExist:
            return Response({"detail": "Não encontrado."}, status=404)
        eventos = t.eventos.order_by("id")
        ev_data = [
            {
                "id": e.id,
                "criado_em": e.criado_em.isoformat() if e.criado_em else None,
                "etapa_codigo": e.etapa_codigo,
                "funil_estagio": e.funil_estagio,
                "tipo_evento": e.tipo_evento,
                "payload": e.payload,
            }
            for e in eventos
        ]
        return Response(
            {
                "id": t.id,
                "telefone": t.telefone,
                "usuario": {
                    "id": t.usuario_id,
                    "username": t.usuario.username if t.usuario else None,
                    "nome": t.usuario.get_full_name() if t.usuario else None,
                },
                "matricula_pap_snapshot": t.matricula_pap_snapshot,
                "bo_usuario_id": t.bo_usuario_id,
                "status": t.status,
                "funil_estagio_max": t.funil_estagio_max,
                "etapa_codigo_atual": t.etapa_codigo_atual,
                "protocolo_pap": t.protocolo_pap,
                "credito_resultado": t.credito_resultado,
                "mensagem_erro": t.mensagem_erro,
                "dados_agregados": t.dados_agregados,
                "iniciado_em": t.iniciado_em.isoformat() if t.iniciado_em else None,
                "finalizado_em": t.finalizado_em.isoformat() if t.finalizado_em else None,
                "eventos": ev_data,
            }
        )
