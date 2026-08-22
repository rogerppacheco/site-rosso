import io
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import AuditoriaLigacao, Venda
from crm_app.cloudflare_r2_service import CloudflareR2Storage
from crm_app.sonax_voice_service import SonaxVoiceService, unpack_recording_zip
from crm_app.zenvia_voice_service import ZenviaVoiceService

logger = logging.getLogger(__name__)


def _is_member(user, groups) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name__in=groups).exists()


def _normalize_phone(raw: Optional[str]) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11):
        return f"55{digits}"
    return digits


def _extract_first(data: Dict[str, Any], keys, default=None):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _auditoria_grupos():
    return ["Diretoria", "Admin", "BackOffice", "Supervisor", "Auditoria", "Qualidade"]


def _sonax_configured() -> bool:
    return bool(
        str(getattr(settings, "SONAX_CLICK2CALL_TOKEN", "") or "").strip()
        or str(getattr(settings, "SONAX_INTEGRATION_TOKEN", "") or "").strip()
    )


def _resolved_voice_provider() -> str:
    p = str(getattr(settings, "AUDITORIA_VOICE_PROVIDER", "sonax") or "sonax").strip().lower()
    if p == "sonax":
        return "sonax"
    if p == "zenvia":
        return "zenvia"
    # auto: Sonax é o provedor operacional da auditoria quando configurado
    if _sonax_configured():
        return "sonax"
    if str(getattr(settings, "ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER", "") or "").strip():
        return "zenvia"
    return "sonax"


def _sonax_ramais_permitidos() -> List[str]:
    raw = getattr(settings, "SONAX_RAMAIS", "101,102,103")
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _merge_webhook_payload(request: HttpRequest) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    try:
        for key in request.query_params:
            merged[str(key)] = request.query_params.get(key)
    except Exception:
        pass
    try:
        body = getattr(request, "data", None)
    except Exception:
        body = None
    if isinstance(body, dict):
        for k, v in body.items():
            merged[str(k)] = v
    return merged


def _webhook_call_id(payload: Dict[str, Any]) -> Optional[str]:
    for key in (
        "id_chamada",
        "ID_CHAMADA",
        "id",
        "chamada_id",
        "call_id",
        "protocolo",
    ):
        val = payload.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return None


def _webhook_recording_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in (
        "link_gravacao",
        "url_gravacao",
        "gravacao_url",
        "link_gravação",
        "recording_url",
        "LINK_GRAVACAO",
        "gravacao",
    ):
        val = payload.get(key)
        if val and isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
            return val.strip()
    return None


def _webhook_duracao(payload: Dict[str, Any]) -> int:
    raw = _extract_first(
        payload,
        ["duracao_segundos", "duracao", "DURACAO_CHAMADA", "duration", "Duracao"],
        default=0,
    )
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        return 0


def _webhook_status_raw(payload: Dict[str, Any]) -> str:
    return str(
        _extract_first(
            payload,
            ["status_chamada", "STATUS_CHAMADA", "status", "Status"],
            default="",
        )
        or ""
    ).strip()


def _webhook_status_atendimento(payload: Dict[str, Any]) -> str:
    return str(
        _extract_first(
            payload,
            ["status_atendimento", "STATUS_ATENDIMENTO", "atendido"],
            default="",
        )
        or ""
    ).strip()


def _parse_provider_datetime(raw: Any) -> Optional[datetime]:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    dt = parse_datetime(text.replace(" ", "T"))
    if dt is None:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _finalizada_por_status(provedor: str, status_provedor: str) -> bool:
    sp = status_provedor.upper()
    if provedor == "SONAX":
        sl = status_provedor.lower()
        if sl in ("desligada", "encerrada", "finalizada", "atendida"):
            return True
        if "deslig" in sl:
            return True
        return False
    return sp in {"ATENDIDA", "FINALIZADA", "ENCERRADA"}


def _cliente_nome_cpf_da_venda(venda: Optional[Venda]) -> tuple[Optional[str], Optional[str]]:
    if not venda:
        return None, None
    # Fonte principal: relacionamento normalizado Venda -> Cliente
    cli = getattr(venda, "cliente", None)
    nome = getattr(cli, "nome_razao_social", None) if cli else None
    cpf = getattr(cli, "cpf_cnpj", None) if cli else None

    # Fallback para bases legadas (campos denormalizados, quando existirem)
    if not nome:
        nome = getattr(venda, "cliente_nome_razao_social", None)
    if not cpf:
        cpf = getattr(venda, "cliente_cpf_cnpj", None)
    return nome, cpf


def _cpf_apenas_digitos(cpf: Optional[str]) -> str:
    return re.sub(r"\D", "", str(cpf or ""))


def _parse_data_iso(value: Optional[str]) -> Optional[date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _periodo_historico_padrao() -> tuple[date, date]:
    hoje = timezone.localdate()
    return hoje.replace(day=1), hoje


def _pedidos_por_cliente_ids(cliente_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    ids = [i for i in {int(x) for x in cliente_ids if x}]
    if not ids:
        return {}
    out: Dict[int, List[Dict[str, Any]]] = {i: [] for i in ids}
    vendas = (
        Venda.objects.filter(cliente_id__in=ids)
        .order_by("-data_criacao")
        .values("id", "cliente_id", "ordem_servico", "data_criacao")
    )
    for v in vendas:
        cid = v["cliente_id"]
        if cid not in out:
            out[cid] = []
        out[cid].append(
            {
                "venda_id": v["id"],
                "ordem_servico": v["ordem_servico"] or None,
                "data_criacao": v["data_criacao"],
            }
        )
    return out


def _pedidos_por_cpf_digitos(cpfs_digitos: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    chaves = [c for c in {c for c in cpfs_digitos if c and len(c) >= 11}]
    if not chaves:
        return {}
    q = Q()
    for d in chaves:
        q |= Q(cliente__cpf_cnpj__icontains=d)
    out: Dict[str, List[Dict[str, Any]]] = {c: [] for c in chaves}
    vendas = (
        Venda.objects.filter(q)
        .select_related("cliente")
        .order_by("-data_criacao")
        .values("id", "ordem_servico", "data_criacao", "cliente__cpf_cnpj")
    )
    for v in vendas:
        cpf_raw = v.get("cliente__cpf_cnpj") or ""
        dig = _cpf_apenas_digitos(cpf_raw)
        if dig not in out:
            continue
        out[dig].append(
            {
                "venda_id": v["id"],
                "ordem_servico": v["ordem_servico"] or None,
                "data_criacao": v["data_criacao"],
            }
        )
    return out


class AuditoriaLigacaoOpcoesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: HttpRequest):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)
        provider = _resolved_voice_provider()
        return Response(
            {
                "voice_provider": provider,
                "sonax_ramais": _sonax_ramais_permitidos() if provider == "sonax" else [],
            }
        )


class AuditoriaLigacaoStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: HttpRequest, venda_id: int):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        venda = Venda.objects.filter(id=venda_id, ativo=True).first()
        if not venda:
            return Response({"detail": "Venda não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        destination = request.data.get("destination_number") or venda.telefone1 or venda.telefone2
        if not destination:
            return Response(
                {"detail": "Venda sem telefone de destino e destination_number não informado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        destination = _normalize_phone(destination)

        provider = _resolved_voice_provider()
        try:
            if provider == "sonax":
                ligacao, provider_resp = self._iniciar_sonax(request, venda, destination)
            else:
                ligacao, provider_resp = self._iniciar_zenvia(request, venda, destination)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Erro ao iniciar ligação (%s): %s", provider, exc)
            return Response(
                {"detail": f"Falha ao iniciar ligação: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "detail": "Ligação iniciada com sucesso.",
                "ligacao_id": ligacao.id,
                "provider_call_id": ligacao.provider_call_id,
                "provedor": ligacao.provedor,
                "warning": (
                    "Provedor não retornou ID da chamada (sem_id). "
                    "Verifique token/IP liberado/ramal e logs do backend."
                    if str(ligacao.provider_call_id).startswith("sem_id_")
                    else None
                ),
                "provider_response": provider_resp,
            },
            status=status.HTTP_201_CREATED,
        )

    def _iniciar_sonax(self, request, venda: Venda, destination: str):
        ramal = request.data.get("sip_extension") or request.data.get("ramal")
        if not ramal:
            raise ValueError("Informe o ramal SIP (campo sip_extension ou ramal).")
        ramal = str(ramal).strip()
        permitidos = _sonax_ramais_permitidos()
        if permitidos and ramal not in permitidos:
            raise ValueError(f"Ramal não permitido. Use um de: {', '.join(permitidos)}")

        sonax = SonaxVoiceService()
        var_tags = {
            "auditoria_venda": str(venda.id),
        }
        provider_resp = sonax.click_to_call(
            destination_digits=destination,
            ramal=ramal,
            var_tags=var_tags,
        )
        call_id = provider_resp.get("id_chamada")
        if not call_id:
            call_id = f"sem_id_{timezone.now().timestamp()}"
            logger.warning(
                "Auditoria Sonax sem id_chamada. venda_id=%s usuario=%s ramal=%s destino=%s debug=%s parsed=%s raw=%s",
                venda.id,
                getattr(request.user, "username", None),
                ramal,
                destination,
                provider_resp.get("debug"),
                provider_resp.get("parsed"),
                (provider_resp.get("raw_text") or "")[:500],
            )

        ligacao = AuditoriaLigacao.objects.create(
            venda=venda,
            auditor=request.user,
            provedor="SONAX",
            provider_call_id=str(call_id),
            numero_origem=ramal,
            numero_destino=destination,
            status="INICIADA",
            consentimento_declarado=bool(request.data.get("consentimento_declarado", True)),
            consentimento_observacao=request.data.get(
                "consentimento_observacao",
                "Cliente informado pelo auditor no início da chamada.",
            ),
            payload_inicio=dict(provider_resp) if isinstance(provider_resp, dict) else {"raw": str(provider_resp)},
        )
        return ligacao, provider_resp

    def _iniciar_zenvia(self, request, venda: Venda, destination: str):
        source = request.data.get("source_number") or getattr(settings, "ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER", "")
        if not source:
            raise ValueError(
                "Defina ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER ou envie source_number no payload."
            )
        source = _normalize_phone(source)
        tags = f"auditoria_venda_{venda.id}"

        service = ZenviaVoiceService()
        provider_resp = service.create_call(
            source_number=source,
            destination_number=destination,
            record_audio=True,
            tags=tags,
            bina=request.data.get("bina"),
        )

        dados = provider_resp.get("dados") if isinstance(provider_resp, dict) else {}
        call_id = _extract_first(
            dados if isinstance(dados, dict) else {},
            ["id", "chamada_id", "call_id"],
            default=_extract_first(provider_resp, ["id", "chamada_id", "call_id"]),
        )
        if call_id is None:
            call_id = f"sem_id_{timezone.now().timestamp()}"

        ligacao = AuditoriaLigacao.objects.create(
            venda=venda,
            auditor=request.user,
            provedor="ZENVIA",
            provider_call_id=str(call_id),
            numero_origem=source,
            numero_destino=destination,
            status="INICIADA",
            consentimento_declarado=bool(request.data.get("consentimento_declarado", True)),
            consentimento_observacao=request.data.get(
                "consentimento_observacao",
                "Auditor informou em voz que a chamada estava sendo gravada.",
            ),
            payload_inicio=provider_resp if isinstance(provider_resp, dict) else {"raw": str(provider_resp)},
        )
        return ligacao, provider_resp


class AuditoriaLigacaoListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: HttpRequest, venda_id: int):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        limite = int(request.GET.get("limite", 30))
        rows = AuditoriaLigacao.objects.filter(venda_id=venda_id).select_related("auditor").order_by("-criado_em")[:limite]
        data = [
            {
                "id": r.id,
                "status": r.status,
                "provedor": r.provedor,
                "provider_call_id": r.provider_call_id,
                "provider_recording_id": r.provider_recording_id,
                "id_contato": r.id_contato,
                "numero_origem": r.numero_origem,
                "numero_destino": r.numero_destino,
                "numero_receptivo": r.numero_receptivo,
                "status_chamada_provedor": r.status_chamada_provedor,
                "status_atendimento": r.status_atendimento,
                "duracao_segundos": r.duracao_segundos,
                "data_inicio_chamada": r.data_inicio_chamada,
                "data_fim_chamada": r.data_fim_chamada,
                "link_gravacao_provedor": r.link_gravacao_provedor,
                "link_gravacao_onedrive": r.link_gravacao_onedrive,
                "auditor": r.auditor.username if r.auditor else None,
                "criado_em": r.criado_em,
            }
            for r in rows
        ]
        return Response({"results": data})


class AuditoriaLigacaoSincronizarView(APIView):
    """
    Endpoint manual para "forçar" o mesmo fluxo do fallback:
    consulta status_chamada e tenta baixar/arquivar gravação via pega_gravacao.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: HttpRequest, ligacao_id: int):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        ligacao = (
            AuditoriaLigacao.objects.filter(id=ligacao_id)
            .select_related("venda", "auditor")
            .first()
        )
        if not ligacao:
            return Response({"detail": "Ligação não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        if ligacao.provedor != "SONAX":
            return Response({"detail": "Sincronização manual disponível apenas para Sonax."}, status=status.HTTP_400_BAD_REQUEST)

        cid = str(ligacao.provider_call_id or "").strip()
        if not cid.isdigit():
            return Response({"detail": "provider_call_id inválido para consulta Sonax."}, status=status.HTTP_400_BAD_REQUEST)

        svc = SonaxVoiceService()
        if not svc.is_recording_download_configured:
            return Response(
                {"detail": "Sonax status/gravação não configurados (SONAX_ID_CLIENTE/SONAX_INTEGRATION_TOKEN)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        st = svc.fetch_call_status(cid)
        status_chamada = (st.get("status_chamada") or "").strip()
        status_atendimento = (st.get("status_atendimento") or "").strip().upper()
        dur = st.get("duracao_segundos")
        data_ini = _parse_provider_datetime(st.get("data_inicio"))
        data_fim = _parse_provider_datetime(st.get("data_fim"))

        finalizada = _finalizada_por_status("SONAX", status_chamada)
        if status_atendimento == "S":
            finalizada = True

        update_fields = []
        if status_chamada:
            ligacao.status_chamada_provedor = status_chamada
            update_fields.append("status_chamada_provedor")
        if status_atendimento:
            ligacao.status_atendimento = status_atendimento
            update_fields.append("status_atendimento")
        if dur not in (None, ""):
            try:
                ligacao.duracao_segundos = int(dur)
                update_fields.append("duracao_segundos")
            except (TypeError, ValueError):
                pass
        if data_ini:
            ligacao.data_inicio_chamada = data_ini
            update_fields.append("data_inicio_chamada")
        if data_fim:
            ligacao.data_fim_chamada = data_fim
            update_fields.append("data_fim_chamada")

        ligacao.status = "FINALIZADA" if finalizada else "PROCESSANDO"
        update_fields.append("status")
        if finalizada:
            ligacao.finalizado_em = timezone.now()
            update_fields.append("finalizado_em")

        ligacao.save(update_fields=list(dict.fromkeys(update_fields + ["atualizado_em"])))

        # Se finalizou e ainda não arquivou, tenta baixar e mandar pro R2
        if finalizada and not ligacao.link_gravacao_onedrive:
            try:
                content, ext = svc.download_recording(cid)
                _upload_bytes_to_r2(ligacao, content, ext)
            except Exception as exc:
                logger.warning("Sincronização manual: falha ao arquivar gravação. ligacao_id=%s call_id=%s err=%s", ligacao.id, cid, exc)

        # Recarrega dados atualizados (pode ter link_onedrive preenchido)
        ligacao.refresh_from_db()
        return Response(
            {
                "id": ligacao.id,
                "status": ligacao.status,
                "provedor": ligacao.provedor,
                "provider_call_id": ligacao.provider_call_id,
                "numero_origem": ligacao.numero_origem,
                "numero_destino": ligacao.numero_destino,
                "status_chamada_provedor": ligacao.status_chamada_provedor,
                "status_atendimento": ligacao.status_atendimento,
                "duracao_segundos": ligacao.duracao_segundos,
                "data_inicio_chamada": ligacao.data_inicio_chamada,
                "data_fim_chamada": ligacao.data_fim_chamada,
                "link_gravacao_provedor": ligacao.link_gravacao_provedor,
                "link_gravacao_onedrive": ligacao.link_gravacao_onedrive,
                "criado_em": ligacao.criado_em,
            }
        )


class AuditoriaLigacaoSincronizarLoteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: HttpRequest):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.tasks import processar_fallback_auditoria_ligacoes_sonax

        limite_raw = request.data.get("limite", 300)
        try:
            limite = max(1, min(int(limite_raw), 1000))
        except (TypeError, ValueError):
            limite = 300

        processar_fallback_auditoria_ligacoes_sonax(
            limite=limite,
            grace_seconds=0,
            include_finalizadas_sem_gravacao=True,
        )
        return Response({"detail": "Sincronização em lote executada.", "limite": limite})


class AuditoriaLigacaoHistoricoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: HttpRequest):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        rows = AuditoriaLigacao.objects.select_related(
            "auditor",
            "venda",
            "venda__cliente",
            "venda__status_tratamento",
            "venda__status_esteira",
        ).all().order_by("criado_em")
        q = str(request.GET.get("q", "") or "").strip()
        if q:
            rows = rows.filter(
                Q(numero_destino__icontains=q)
                | Q(numero_origem__icontains=q)
                | Q(provider_call_id__icontains=q)
                | Q(venda__cliente__nome_razao_social__icontains=q)
                | Q(venda__cliente__cpf_cnpj__icontains=q)
                | Q(venda__ordem_servico__icontains=q)
            )

        status_q = str(request.GET.get("status", "") or "").strip()
        if status_q:
            rows = rows.filter(status=status_q)

        auditor_q = str(request.GET.get("auditor", "") or "").strip()
        if auditor_q:
            rows = rows.filter(auditor__username__icontains=auditor_q)

        status_tratamento_id = str(request.GET.get("status_tratamento_id", "") or "").strip()
        if status_tratamento_id.isdigit():
            rows = rows.filter(venda__status_tratamento_id=int(status_tratamento_id))

        status_esteira_id = str(request.GET.get("status_esteira_id", "") or "").strip()
        if status_esteira_id.isdigit():
            rows = rows.filter(venda__status_esteira_id=int(status_esteira_id))

        dt_ini = _parse_data_iso(request.GET.get("data_inicio"))
        dt_fim = _parse_data_iso(request.GET.get("data_fim"))
        if dt_ini is None and dt_fim is None:
            dt_ini, dt_fim = _periodo_historico_padrao()
        elif dt_ini is None:
            dt_ini = dt_fim
        elif dt_fim is None:
            dt_fim = dt_ini
        if dt_ini and dt_fim and dt_ini > dt_fim:
            dt_ini, dt_fim = dt_fim, dt_ini
        if dt_ini and dt_fim:
            rows = rows.filter(criado_em__date__gte=dt_ini, criado_em__date__lte=dt_fim)

        page = max(1, int(request.GET.get("page", 1) or 1))
        page_size = min(max(1, int(request.GET.get("page_size", 25) or 25)), 100)
        paginator = Paginator(rows, page_size)
        page_obj = paginator.get_page(page)

        cliente_ids: List[int] = []
        cpfs_sem_cliente: List[str] = []
        for r in page_obj.object_list:
            venda = r.venda
            if venda and getattr(venda, "cliente_id", None):
                cliente_ids.append(int(venda.cliente_id))
            else:
                _nome, cpf = _cliente_nome_cpf_da_venda(venda)
                dig = _cpf_apenas_digitos(cpf)
                if dig:
                    cpfs_sem_cliente.append(dig)

        pedidos_cliente = _pedidos_por_cliente_ids(cliente_ids)
        pedidos_cpf = _pedidos_por_cpf_digitos(cpfs_sem_cliente)

        data = []
        for r in page_obj.object_list:
            nome, cpf = _cliente_nome_cpf_da_venda(r.venda)
            venda = r.venda
            if venda and getattr(venda, "cliente_id", None):
                pedidos = pedidos_cliente.get(int(venda.cliente_id), [])
            else:
                pedidos = pedidos_cpf.get(_cpf_apenas_digitos(cpf), [])
            st_trat = getattr(venda, "status_tratamento", None) if venda else None
            st_est = getattr(venda, "status_esteira", None) if venda else None
            data.append(
                {
                    "id": r.id,
                    "venda_id": r.venda_id,
                    "cliente_nome": nome,
                    "cliente_cpf_cnpj": cpf,
                    "pedidos_cpf": pedidos,
                    "status_tratamento_id": st_trat.id if st_trat else None,
                    "status_tratamento_nome": getattr(st_trat, "nome", None) if st_trat else None,
                    "status_esteira_id": st_est.id if st_est else None,
                    "status_esteira_nome": getattr(st_est, "nome", None) if st_est else None,
                    "status": r.status,
                    "provedor": r.provedor,
                    "provider_call_id": r.provider_call_id,
                    "numero_origem": r.numero_origem,
                    "numero_destino": r.numero_destino,
                    "numero_receptivo": r.numero_receptivo,
                    "status_chamada_provedor": r.status_chamada_provedor,
                    "status_atendimento": r.status_atendimento,
                    "duracao_segundos": r.duracao_segundos,
                    "data_inicio_chamada": r.data_inicio_chamada,
                    "data_fim_chamada": r.data_fim_chamada,
                    "link_gravacao_onedrive": r.link_gravacao_onedrive,
                    "link_gravacao_provedor": r.link_gravacao_provedor,
                    "auditor": r.auditor.username if r.auditor else None,
                    "criado_em": r.criado_em,
                }
            )

        return Response(
            {
                "count": paginator.count,
                "page": page_obj.number,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
                "data_inicio": dt_ini.isoformat() if dt_ini else None,
                "data_fim": dt_fim.isoformat() if dt_fim else None,
                "results": data,
            }
        )


class AuditoriaLigacaoWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request: HttpRequest):
        return self._process(request)

    def post(self, request: HttpRequest):
        return self._process(request)

    def _process(self, request: HttpRequest):
        z_secret = (getattr(settings, "ZENVIA_VOICE_WEBHOOK_SECRET", "") or "").strip()
        s_secret = (getattr(settings, "SONAX_WEBHOOK_SECRET", "") or "").strip()
        configured = [s for s in (z_secret, s_secret) if s]

        # O Sonax pode enviar `secret` tanto na querystring quanto no body (depende do tipo de integração).
        received = ""
        received_src = ""
        q_secret = request.query_params.get("secret") if hasattr(request, "query_params") else None
        h_secret = request.headers.get("X-Webhook-Secret") if hasattr(request, "headers") else None
        if h_secret:
            received = str(h_secret).strip()
            received_src = "header"
        elif q_secret:
            received = str(q_secret).strip()
            received_src = "query"
        else:
            # Tenta body (form/json). Pode falhar por Content-Type inesperado; por isso try/except.
            try:
                body = getattr(request, "data", None)
            except Exception:
                body = None
            if isinstance(body, dict):
                for k in ("secret", "Secret", "WEBHOOK_SECRET", "webhook_secret"):
                    if k in body and body[k] not in (None, ""):
                        received = str(body.get(k)).strip()
                        received_src = "body"
                        break

        if configured:
            if received not in configured:
                # Importante: não registrar o secret em claro
                logger.warning(
                    "Webhook auditoria recusado (secret mismatch). method=%s path=%s received_src=%s configured_count=%s payload_keys=%s",
                    request.method,
                    getattr(request, "path", ""),
                    received_src,
                    len(configured),
                    list(request.query_params.keys())[:20],
                )
                return Response({"detail": "Webhook não autorizado."}, status=status.HTTP_401_UNAUTHORIZED)

        payload = _merge_webhook_payload(request)
        call_id = _webhook_call_id(payload)
        logger.info(
            "Webhook auditoria recebido. method=%s provider_guess=%s call_id=%s payload_keys=%s duracao=%s status_chamada=%s status_atendimento=%s recording_url_set=%s",
            request.method,
            ligacao.provedor if (False) else "unknown",
            call_id,
            list(payload.keys())[:25],
            (_webhook_duracao(payload) if payload else 0),
            _webhook_status_raw(payload)[:60] if payload else "",
            _webhook_status_atendimento(payload)[:60] if payload else "",
            bool(_webhook_recording_url(payload)),
        )
        if not call_id:
            logger.warning(
                "Webhook auditoria sem call_id/id_chamada. method=%s path=%s payload=%s",
                request.method,
                getattr(request, "path", ""),
                {k: payload.get(k) for k in list(payload.keys())[:20]},
            )
            return Response({"detail": "call_id / id_chamada não encontrado no webhook."}, status=status.HTTP_400_BAD_REQUEST)

        ligacao = AuditoriaLigacao.objects.filter(provider_call_id=str(call_id)).order_by("-id").first()
        if not ligacao:
            logger.warning(
                "Webhook auditoria call_id não encontrado no banco. call_id=%s method=%s path=%s",
                call_id,
                request.method,
                getattr(request, "path", ""),
            )
            return Response({"detail": "Ligação não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        status_provedor = _webhook_status_raw(payload)
        status_atendimento = _webhook_status_atendimento(payload).upper()
        finalizada = _finalizada_por_status(ligacao.provedor, status_provedor)
        if status_atendimento == "S":
            finalizada = True
        if not status_provedor and _webhook_recording_url(payload):
            finalizada = True
        duracao = _webhook_duracao(payload)
        recording_url = _webhook_recording_url(payload)
        data_inicio = _parse_provider_datetime(
            _extract_first(payload, ["data_inicio", "DATA_INICIO", "start_time"], default=None)
        )
        data_fim = _parse_provider_datetime(
            _extract_first(payload, ["data_fim", "DATA_FIM", "end_time"], default=None)
        )
        id_contato = _extract_first(payload, ["id_contato", "ID_CONTATO", "id_contato2", "ID_CONTATO2"], default=None)
        numero_receptivo = _extract_first(payload, ["numero_rec", "NUMERO_REC"], default=None)

        status_interno = "FINALIZADA" if finalizada else "PROCESSANDO"

        with transaction.atomic():
            ligacao.payload_webhook = payload
            ligacao.status = status_interno
            ligacao.finalizado_em = timezone.now()
            ligacao.duracao_segundos = duracao
            ligacao.status_chamada_provedor = status_provedor or None
            ligacao.status_atendimento = status_atendimento or None
            ligacao.data_inicio_chamada = data_inicio
            ligacao.data_fim_chamada = data_fim
            ligacao.id_contato = str(id_contato).strip() if id_contato not in (None, "") else ligacao.id_contato
            ligacao.numero_receptivo = (
                str(numero_receptivo).strip() if numero_receptivo not in (None, "") else ligacao.numero_receptivo
            )
            if recording_url:
                ligacao.link_gravacao_provedor = recording_url
            ligacao.save(update_fields=[
                "payload_webhook",
                "status",
                "finalizado_em",
                "duracao_segundos",
                "status_chamada_provedor",
                "status_atendimento",
                "data_inicio_chamada",
                "data_fim_chamada",
                "id_contato",
                "numero_receptivo",
                "link_gravacao_provedor",
                "atualizado_em",
            ])

        logger.info(
            "Webhook auditoria processado. call_id=%s ligacao_id=%s provedor=%s status_provedor=%s status_atendimento=%s duracao=%s recording_url=%s",
            call_id,
            ligacao.id,
            ligacao.provedor,
            status_provedor,
            status_atendimento,
            duracao,
            ("set" if ligacao.link_gravacao_provedor else "none"),
        )

        if ligacao.link_gravacao_provedor:
            try:
                _sync_recording_to_r2(ligacao)
            except Exception as exc:
                logger.exception("Falha ao sincronizar gravação no R2: %s", exc)
        elif ligacao.provedor == "SONAX" and finalizada:
            try:
                _try_sonax_download_and_archive(ligacao)
            except Exception as exc:
                logger.exception("Falha ao baixar gravação Sonax (pega_gravacao): %s", exc)

        return Response({"detail": "Webhook processado."}, status=status.HTTP_200_OK)


def _upload_bytes_to_r2(ligacao: AuditoriaLigacao, data: bytes, extension: str) -> None:
    venda = ligacao.venda
    nome_cliente = str(getattr(venda, "cliente_nome_razao_social", "") or "").strip()
    cpf_cnpj = re.sub(r"\D", "", str(getattr(venda, "cliente_cpf_cnpj", "") or ""))
    cliente_token = re.sub(r"[^A-Za-z0-9_-]+", "_", (nome_cliente or "CLIENTE").upper()).strip("_")[:40]
    if not cliente_token:
        cliente_token = f"CLIENTE_{ligacao.venda_id}"
    cliente_folder = f"{cliente_token}_{cpf_cnpj}" if cpf_cnpj else f"{cliente_token}_VENDA_{ligacao.venda_id}"
    call_stamp = (ligacao.data_inicio_chamada or ligacao.criado_em or timezone.now()).strftime("%Y%m%d_%H%M%S")
    filename = f"{call_stamp}_tentativa_{ligacao.id}_{ligacao.provider_call_id}{extension}"
    folder_name = (
        f"{getattr(settings, 'AUDITORIA_R2_FOLDER', 'Auditoria_Ligacoes')}/"
        f"{cliente_folder}/{timezone.localdate().isoformat()}"
    )
    file_obj = io.BytesIO(data)
    file_obj.seek(0)
    uploader = CloudflareR2Storage()
    web_url = uploader.upload_file(file_obj=file_obj, folder_name=folder_name, filename=filename)

    ligacao.link_gravacao_onedrive = web_url
    ligacao.status = "ARQUIVADA"
    if not ligacao.finalizado_em:
        ligacao.finalizado_em = timezone.now()
    ligacao.save(update_fields=["link_gravacao_onedrive", "status", "finalizado_em", "atualizado_em"])


def _sync_recording_to_r2(ligacao: AuditoriaLigacao) -> None:
    url = ligacao.link_gravacao_provedor
    if not url or ligacao.link_gravacao_onedrive:
        return

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    extension = ".mp3"
    if "wav" in content_type:
        extension = ".wav"
    elif "ogg" in content_type:
        extension = ".ogg"

    if response.content[:2] == b"PK":
        prefer_mp3 = bool(getattr(settings, "SONAX_RECORDING_PREFER_MP3", True))
        content, extension = unpack_recording_zip(response.content, prefer_mp3=prefer_mp3)
        _upload_bytes_to_r2(ligacao, content, extension)
        return

    _upload_bytes_to_r2(ligacao, response.content, extension)


def _try_sonax_download_and_archive(ligacao: AuditoriaLigacao) -> None:
    if ligacao.link_gravacao_onedrive or ligacao.provedor != "SONAX":
        return
    cid = str(ligacao.provider_call_id or "")
    if not cid or cid.startswith("sem_id_"):
        return
    svc = SonaxVoiceService()
    if not svc.is_recording_download_configured:
        logger.warning("Sonax pega_gravacao: credenciais id_cliente/token não configuradas.")
        return
    content, ext = svc.download_recording(cid)
    _upload_bytes_to_r2(ligacao, content, ext)
