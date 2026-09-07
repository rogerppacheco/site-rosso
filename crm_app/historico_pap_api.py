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
        from crm_app.historico_pap_service import busca_em_andamento, obter_status_sessao_pap, serializar_busca
        from crm_app.models import HistoricoPapBusca, HistoricoPapPedido
        from crm_app.pool_historico_pap import candidatos_historico_pap, resumo_pool

        hoje = date.today()
        busca = busca_em_andamento()
        ultima = HistoricoPapBusca.objects.select_related("login_pap").order_by("-iniciado_em").first()
        pool = resumo_pool()
        cand = list(candidatos_historico_pap())
        mat_cand = getattr(cand[0], "matricula_pap", "") if cand else ""
        sessao_info = obter_status_sessao_pap(mat_cand)

        return Response(
            {
                "tipos": ["VENDA", "INTERESSE", "PRE_VENDA"],
                "data_inicio": date(hoje.year, hoje.month, 1).isoformat(),
                "data_fim": hoje.isoformat(),
                "max_dias": MAX_DIAS_BUSCA,
                "tem_credencial_pap": pool["disponiveis"] > 0 or pool["em_uso"] > 0,
                "pool": pool,
                "sessao_pap": sessao_info,
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
        token_manual = (
            data.get("token_manual")
            or data.get("token")
            or request.headers.get("X-PAP-Token")
            or ""
        ).strip()

        from crm_app.historico_pap_service import criar_e_iniciar_busca

        exec_id, err = criar_e_iniciar_busca(
            request.user,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pdv="",
            tipos=tipos,
            token_manual=token_manual,
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
                "token_manual_utilizado": bool(token_manual),
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


class FunilHistoricoPapPedidosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)

        from crm_app.historico_pap_service import map_pedido_api, normalizar_pedido
        from crm_app.models import HistoricoPapBusca, HistoricoPapPedido

        busca_id = request.query_params.get("busca_id")
        tipo = request.query_params.get("tipo")

        busca = None
        novos_set: set[str] = set()
        if busca_id:
            busca = HistoricoPapBusca.objects.filter(pk=busca_id).first()
        else:
            busca = HistoricoPapBusca.objects.order_by("-iniciado_em").first()

        if busca and busca.novos_numeros:
            novos_set = {normalizar_pedido(n) for n in busca.novos_numeros if n}

        qs = HistoricoPapPedido.objects.all()
        if tipo:
            qs = qs.filter(tipo_venda__iexact=tipo)

        qs = qs.order_by("-capturado_em")[:500]

        res = []
        for p in qs:
            payload = p.payload or {}
            mapped = map_pedido_api(payload, p.tipo_venda)
            num_norm = normalizar_pedido(p.numero_pedido)

            cliente_val = mapped.get("cliente") or payload.get("cliente") or payload.get("nomeCliente") or "Desconhecido"
            doc_val = mapped.get("cpf") or mapped.get("documento") or payload.get("cpf") or payload.get("documento") or ""
            status_val = mapped.get("status_primario") or p.status or payload.get("chaveStatusPrimario") or payload.get("status") or "Desconhecido"

            res.append({
                "id": p.id,
                "protocolo": mapped.get("pedido") or p.numero_pedido,
                "cliente": cliente_val,
                "documento": doc_val,
                "tipo_venda": p.tipo_venda,
                "status_primario": status_val,
                "novo_nesta_busca": num_norm in novos_set,
                "data_status": mapped.get("data_pedido") or "",
            })

        return Response(res)


class FunilHistoricoPapImportarView(APIView):
    """Dispara busca PAP de VENDAS e importa pedidos locais para o CRM."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"error": "Sem permissão."}, status=403)

        from datetime import timedelta

        from crm_app.historico_pap_service import busca_em_andamento, criar_e_iniciar_busca
        from crm_app.models import HistoricoPapPedido
        from crm_app.services_sincronizacao import sincronizar_pedido_pap_para_venda

        if busca_em_andamento():
            return Response(
                {"error": "Já existe uma busca no PAP em andamento. Aguarde terminar para importar."},
                status=400,
            )

        try:
            periodo = request.data.get("periodo", "hoje")
            hoje = date.today()
            if periodo == "mes":
                data_inicio = date(hoje.year, hoje.month, 1)
            elif periodo == "semana":
                data_inicio = hoje - timedelta(days=7)
            elif periodo == "ontem":
                data_inicio = hoje - timedelta(days=1)
            else:
                data_inicio = hoje

            criar_e_iniciar_busca(
                request.user,
                data_inicio=data_inicio,
                data_fim=hoje,
                pdv="",
                tipos=["VENDA"],
                token_manual="",
            )
        except Exception as e:
            logger.error("Erro ao iniciar busca online do PAP: %s", e, exc_info=True)

        pedidos = HistoricoPapPedido.objects.filter(tipo_venda="VENDA").order_by("-capturado_em")[:100]

        sucessos = 0
        falhas = 0
        erros_msgs: list[str] = []

        for p in pedidos:
            try:
                res = sincronizar_pedido_pap_para_venda(p.id)
                if res.get("sucesso"):
                    sucessos += 1
                else:
                    msg = res.get("mensagem") or ""
                    if "já existe" not in msg:
                        falhas += 1
                        erros_msgs.append(f"Pedido {p.numero_pedido}: {msg}")
            except Exception as e:
                logger.error("Erro ao importar pedido %s: %s", p.id, e, exc_info=True)
                falhas += 1

        msg_final = f"Busca online iniciada (pode levar 1 minuto). Do banco local, {sucessos} novas vendas criadas."
        if falhas > 0:
            msg_final += f" ({falhas} com erro)."

        return Response({"sucesso": True, "mensagem": msg_final, "erros": erros_msgs})
