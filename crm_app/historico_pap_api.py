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
        from crm_app.historico_pap_service import (
            busca_em_andamento,
            obter_pausa_rotina_automatica,
            obter_status_sessao_pap,
            serializar_busca,
        )
        from crm_app.models import HistoricoPapBusca, HistoricoPapPedido
        from crm_app.pool_historico_pap import candidatos_historico_pap, resumo_pool

        hoje = date.today()
        busca = busca_em_andamento()
        ultima = HistoricoPapBusca.objects.select_related("login_pap").order_by("-iniciado_em").first()
        pool = resumo_pool()
        cand = list(candidatos_historico_pap())
        mat_cand = getattr(cand[0], "matricula_pap", "") if cand else ""
        sessao_info = obter_status_sessao_pap(mat_cand)
        pausa_rotina = obter_pausa_rotina_automatica()

        return Response(
            {
                "tipos": ["VENDA", "INTERESSE", "PRE_VENDA"],
                "data_inicio": date(hoje.year, hoje.month, 1).isoformat(),
                "data_fim": hoje.isoformat(),
                "max_dias": MAX_DIAS_BUSCA,
                "tem_credencial_pap": pool["disponiveis"] > 0 or pool["em_uso"] > 0,
                "pool": pool,
                "sessao_pap": sessao_info,
                "rotina_automatica_pausada": pausa_rotina,
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
        from crm_app.historico_pap_service import xlsx_novos_da_busca, xlsx_periodo_da_busca
        from crm_app.models import HistoricoPapBusca

        busca_id = request.query_params.get("id") or request.query_params.get("busca_id")
        escopo = (request.query_params.get("escopo") or "periodo").strip().lower()
        if busca_id:
            busca = HistoricoPapBusca.objects.filter(pk=busca_id).first()
        else:
            busca = HistoricoPapBusca.objects.filter(status=HistoricoPapBusca.STATUS_CONCLUIDO).order_by("-iniciado_em").first()
        if not busca:
            return Response({"error": "Nenhuma busca concluída para baixar."}, status=404)
        try:
            if escopo in ("novos", "novo", "new"):
                blob, nome = xlsx_novos_da_busca(busca.id)
                qtd = busca.novos
            else:
                blob, nome, qtd = xlsx_periodo_da_busca(busca.id)
        except Exception:
            logger.exception("Falha ao montar Excel do histórico PAP")
            return Response({"error": "Não foi possível montar a planilha."}, status=400)
        return Response(
            {
                "success": True,
                "nome_arquivo": nome,
                "linhas": qtd,
                "novos": busca.novos,
                "encontrados": busca.encontrados,
                "escopo": "novos" if escopo in ("novos", "novo", "new") else "periodo",
                "busca_id": busca.id,
                "data_inicio": busca.data_inicio.isoformat() if busca.data_inicio else "",
                "data_fim": busca.data_fim.isoformat() if busca.data_fim else "",
                "arquivo_base64": base64.b64encode(blob).decode("ascii"),
                "grava_venda": False,
            }
        )


def filtrar_pedidos_funil(qp) -> dict:
    """Aplica os filtros da tela do Funil (busca, situação, período por Data do pedido, status).

    Retorna o queryset do tipo pedido (`qs_tipo`), o queryset de todos os tipos com os
    mesmos filtros (`base`, para as contagens das abas) e os dados auxiliares da tela.
    """
    from django.db.models import F, Q, TextField, Value
    from django.db.models.fields.json import KeyTextTransform
    from django.db.models.functions import Coalesce, NullIf

    from crm_app.historico_pap_service import normalizar_pedido
    from crm_app.models import HistoricoPapBusca, HistoricoPapPedido

    busca_id = qp.get("busca_id")
    tipo = (qp.get("tipo") or "").strip().upper()

    if busca_id:
        busca = HistoricoPapBusca.objects.filter(pk=busca_id).first()
    else:
        busca = HistoricoPapBusca.objects.order_by("-iniciado_em").first()

    novos_set: set[str] = set()
    novos_lookup: set[str] = set()
    if busca and busca.novos_numeros:
        novos_set = {normalizar_pedido(n) for n in busca.novos_numeros if n}
        novos_lookup = novos_set | {str(n).strip() for n in busca.novos_numeros if n}

    base = HistoricoPapPedido.objects.annotate(
        status_exibicao=Coalesce(
            NullIf(KeyTextTransform("chaveStatusPrimario", "payload"), Value("")),
            NullIf(F("status"), Value("")),
            NullIf(KeyTextTransform("status", "payload"), Value("")),
            output_field=TextField(),
        )
    )

    termo = (qp.get("q") or "").strip()
    if termo:
        digitos = "".join(c for c in termo if c.isdigit())
        filtro = (
            Q(numero_pedido__icontains=termo)
            | Q(payload__cliente__icontains=termo)
            | Q(payload__dadosCliente__nome__icontains=termo)
        )
        if len(digitos) >= 3:
            filtro |= (
                Q(numero_pedido__icontains=digitos)
                | Q(payload__cpf__icontains=digitos)
                | Q(payload__dadosCliente__cpf__icontains=digitos)
                | Q(payload__produtos__bandaLarga__osInstalacao__icontains=digitos)
            )
        base = base.filter(filtro)

    situacao = (qp.get("situacao") or "").strip().lower()
    if situacao == "novos":
        base = base.filter(numero_pedido__in=novos_lookup)
    elif situacao == "base":
        base = base.exclude(numero_pedido__in=novos_lookup)

    data_de = _parse_date(qp.get("de"), None)
    data_ate = _parse_date(qp.get("ate"), None)
    if data_de:
        base = base.filter(data_criacao_pap__date__gte=data_de)
    if data_ate:
        base = base.filter(data_criacao_pap__date__lte=data_ate)

    qs_tipo = base.filter(tipo_venda__iexact=tipo) if tipo else base
    status_opcoes = sorted(
        {s for s in qs_tipo.order_by().values_list("status_exibicao", flat=True).distinct() if s},
        key=str.lower,
    )

    status_filtro = (qp.get("status") or "").strip()
    if status_filtro:
        base = base.filter(status_exibicao__iexact=status_filtro)
        qs_tipo = qs_tipo.filter(status_exibicao__iexact=status_filtro)

    return {
        "tipo": tipo,
        "busca": busca,
        "novos_set": novos_set,
        "base": base,
        "qs_tipo": qs_tipo,
        "status_opcoes": status_opcoes,
        "data_de": data_de,
        "data_ate": data_ate,
    }


def meses_disponiveis_funil(tipo: str) -> list[dict]:
    """Meses (pela Data do pedido) que já existem na base para o tipo, com a quantidade."""
    from django.db.models import Count
    from django.db.models.functions import TruncMonth

    from crm_app.models import HistoricoPapPedido

    qs = HistoricoPapPedido.objects.filter(data_criacao_pap__isnull=False)
    if tipo:
        qs = qs.filter(tipo_venda__iexact=tipo)
    linhas = (
        qs.annotate(mes=TruncMonth("data_criacao_pap"))
        .values("mes")
        .annotate(total=Count("id"))
        .order_by("-mes")
    )
    return [
        {"mes": linha["mes"].strftime("%Y-%m"), "total": linha["total"]}
        for linha in linhas
        if linha["mes"]
    ]


class FunilHistoricoPapPedidosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)

        from django.db.models import Count, F

        from crm_app.historico_pap_service import map_pedido_api, normalizar_pedido
        from crm_app.models import HistoricoPapPedido

        qp = request.query_params
        f = filtrar_pedidos_funil(qp)
        qs_tipo = f["qs_tipo"]
        novos_set = f["novos_set"]
        busca = f["busca"]

        contagens = {t: 0 for t, _ in HistoricoPapPedido.TIPO_CHOICES}
        for t, n in f["base"].order_by().values_list("tipo_venda").annotate(n=Count("id")):
            chave = (t or "").upper()
            contagens[chave] = contagens.get(chave, 0) + n

        if (qp.get("ordem") or "").strip().lower() == "antigos":
            ordenacao = [F("data_criacao_pap").asc(nulls_last=True), "id"]
        else:
            ordenacao = [F("data_criacao_pap").desc(nulls_last=True), "-id"]

        try:
            page_size = int(qp.get("page_size") or 25)
        except (TypeError, ValueError):
            page_size = 25
        page_size = max(10, min(page_size, 200))
        total = qs_tipo.count()
        total_pages = max(1, -(-total // page_size))
        try:
            page = int(qp.get("page") or 1)
        except (TypeError, ValueError):
            page = 1
        page = max(1, min(page, total_pages))
        inicio = (page - 1) * page_size
        qs = qs_tipo.order_by(*ordenacao)[inicio:inicio + page_size]

        from crm_app.services.funil_template_envio_service import enriquecer_linha_interesse

        res = []
        for p in qs:
            payload = p.payload or {}
            mapped = map_pedido_api(payload, p.tipo_venda)
            mapped["tipo_venda"] = p.tipo_venda or mapped.get("tipo_venda")
            num_norm = normalizar_pedido(p.numero_pedido)

            cliente_val = mapped.get("cliente") or payload.get("cliente") or payload.get("nomeCliente") or "Desconhecido"
            doc_val = mapped.get("cpf") or mapped.get("documento") or payload.get("cpf") or payload.get("documento") or ""
            status_val = p.status_exibicao or "Desconhecido"
            # Etapa do fluxo de interesse no PAP (ex.: FROM_ANALISE_CREDITO).
            # Fallback: status secundário (INTERESSE_AUTOMATICO / INTERESSE_ENCERRADO).
            etapa_val = (
                payload.get("etapaInteresse")
                or mapped.get("status_secundario")
                or payload.get("subStatus")
                or payload.get("chaveStatusSecundario")
                or payload.get("statusSecundario")
                or ""
            )

            envio = {}
            if (p.tipo_venda or "").upper() == "INTERESSE":
                try:
                    envio = enriquecer_linha_interesse(mapped, pedido_id=p.id) or {}
                except Exception:
                    envio = {}

            res.append({
                "id": p.id,
                "protocolo": mapped.get("pedido") or p.numero_pedido,
                "cliente": cliente_val,
                "documento": doc_val,
                "os_instalacao": mapped.get("os_instalacao") or "",
                "tipo_venda": p.tipo_venda,
                "status_primario": status_val,
                "etapa": etapa_val,
                "status_secundario": etapa_val,
                "novo_nesta_busca": num_norm in novos_set,
                "data_status": mapped.get("data_pedido") or "",
                **envio,
            })

        return Response({
            "results": res,
            "count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "contagens": contagens,
            "status_opcoes": f["status_opcoes"],
            "meses": meses_disponiveis_funil(f["tipo"]),
            "busca_id": busca.id if busca else None,
        })


class FunilHistoricoPapExportarView(APIView):
    """Excel com TODOS os pedidos que atendem aos filtros da tela (sem paginação)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)

        from django.db.models import F

        from crm_app.historico_pap import map_pedido_api, montar_xlsx_historico

        f = filtrar_pedidos_funil(request.query_params)
        qs = f["qs_tipo"].order_by(F("data_criacao_pap").asc(nulls_last=True), "numero_pedido")
        linhas = []
        for p in qs.iterator(chunk_size=500):
            if p.payload:
                linhas.append(map_pedido_api(p.payload, p.tipo_venda))
            else:
                linhas.append({"tipo_venda": p.tipo_venda, "pedido": p.numero_pedido, "status": p.status})
        if not linhas:
            return Response({"error": "Nenhum pedido com esses filtros para exportar."}, status=404)

        partes = ["Historico_PAP", f["tipo"] or "TODOS"]
        if f["data_de"] or f["data_ate"]:
            partes.append(f"{f['data_de'] or 'inicio'}_a_{f['data_ate'] or 'hoje'}")
        try:
            blob = montar_xlsx_historico(linhas)
        except Exception:
            logger.exception("Falha ao montar Excel do Funil")
            return Response({"error": "Não foi possível montar a planilha."}, status=400)
        return Response({
            "success": True,
            "nome_arquivo": "_".join(partes) + ".xlsx",
            "linhas": len(linhas),
            "arquivo_base64": base64.b64encode(blob).decode("ascii"),
        })


class FunilHistoricoPapImportarView(APIView):
    """Dispara busca PAP de VENDAS e/ou importa pedidos locais para o CRM."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"error": "Sem permissão."}, status=403)

        from datetime import timedelta

        from crm_app.historico_pap_service import busca_em_andamento, criar_e_iniciar_busca, serializar_busca
        from crm_app.models import HistoricoPapBusca, HistoricoPapPedido
        from crm_app.services_sincronizacao import sincronizar_pedido_pap_para_venda

        data = request.data if isinstance(request.data, dict) else {}
        apenas_sincronizar = bool(data.get("apenas_sincronizar") or data.get("somente_sync"))
        busca_id = data.get("busca_id") or data.get("id")

        def _sincronizar_locais(*, so_novos_da_busca=None):
            if so_novos_da_busca:
                numeros = [str(n) for n in (so_novos_da_busca or []) if n]
                pedidos = list(
                    HistoricoPapPedido.objects.filter(
                        tipo_venda="VENDA",
                        numero_pedido__in=numeros,
                    ).order_by("-capturado_em")[:200]
                )
            else:
                pedidos = list(
                    HistoricoPapPedido.objects.filter(tipo_venda="VENDA").order_by("-capturado_em")[:100]
                )

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
            return sucessos, falhas, erros_msgs

        # Apenas sincroniza o que já está no banco (após busca concluir no front)
        if apenas_sincronizar:
            novos_numeros = None
            if busca_id:
                busca = HistoricoPapBusca.objects.filter(pk=busca_id).first()
                if busca and busca.novos_numeros:
                    novos_numeros = busca.novos_numeros
            sucessos, falhas, erros_msgs = _sincronizar_locais(so_novos_da_busca=novos_numeros)
            msg = f"{sucessos} novas vendas criadas a partir do histórico PAP."
            if falhas:
                msg += f" ({falhas} com erro)."
            return Response(
                {
                    "sucesso": True,
                    "mensagem": msg,
                    "criadas": sucessos,
                    "falhas": falhas,
                    "erros": erros_msgs,
                }
            )

        if busca_em_andamento():
            atual = busca_em_andamento()
            return Response(
                {
                    "error": "Já existe uma busca no PAP em andamento. Aguarde terminar.",
                    "busca_id": getattr(atual, "id", None),
                    "status": serializar_busca(atual, em_andamento=True) if atual else None,
                },
                status=409,
            )

        from django.utils import timezone

        periodo = data.get("periodo", "hoje")
        hoje = timezone.localdate()
        data_fim = hoje
        if periodo == "personalizado":
            data_inicio = _parse_date(str(data.get("data_inicio") or ""), None)
            data_fim = _parse_date(str(data.get("data_fim") or ""), None)
            if not data_inicio or not data_fim:
                return Response(
                    {"error": "Informe data inicial e final válidas para o período específico.", "sucesso": False},
                    status=400,
                )
            if data_fim > hoje:
                return Response(
                    {"error": "A data final não pode ser posterior a hoje.", "sucesso": False},
                    status=400,
                )
        elif periodo == "mes":
            data_inicio = date(hoje.year, hoje.month, 1)
        elif periodo == "semana":
            data_inicio = hoje - timedelta(days=7)
        elif periodo == "ontem":
            data_inicio = hoje - timedelta(days=1)
        else:
            data_inicio = hoje

        busca_id_novo, err_busca = criar_e_iniciar_busca(
            request.user,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pdv="",
            tipos=["VENDA"],
            token_manual="",
        )
        if err_busca:
            logger.warning("Busca online do PAP não iniciada: %s", err_busca)
            return Response({"error": err_busca, "sucesso": False}, status=400)

        return Response(
            {
                "sucesso": True,
                "em_andamento": True,
                "busca_id": busca_id_novo,
                "periodo": periodo,
                "data_inicio": data_inicio.isoformat(),
                "data_fim": hoje.isoformat(),
                "mensagem": (
                    "Busca no PAP iniciada. Aguarde a coleta pela SPA "
                    "(pode levar 1–2 minutos)."
                ),
            },
            status=202,
        )
