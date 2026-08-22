"""
Processamento de jobs da fila PAP (serviço dedicado).
"""
from __future__ import annotations

import logging
import traceback

from django.utils import timezone

from crm_app.db_resilience import (
    force_close_db_connections,
    is_db_connection_lost,
    retry_on_db_connection_error,
)
from crm_app.pap_job_fila import PapJobFila

logger = logging.getLogger(__name__)


def _notificar_falha_definitiva(job: PapJobFila) -> None:
    """Evita deixar o usuário aguardando quando o handler nem consegue iniciar."""
    payload = job.payload or {}
    telefone = str(payload.get("telefone") or job.telefone or "").strip()
    if not telefone:
        return

    try:
        from crm_app.models import SessaoWhatsapp
        from crm_app.whatsapp_service import WhatsAppService

        mensagens = {
            "analise_credito": (
                "❌ Não foi possível processar a consulta de crédito agora. "
                "Digite *CRÉDITO* para tentar novamente."
            ),
            "status_online": (
                "❌ Não foi possível concluir a consulta de status agora. "
                "Digite *STATUS* para tentar novamente."
            ),
            "consulta_pedido": (
                "❌ Não foi possível concluir a consulta do pedido agora. "
                "Tente novamente em alguns instantes."
            ),
        }
        mensagem = mensagens.get(
            job.tipo,
            "❌ Não foi possível concluir sua consulta agora. Tente novamente.",
        )
        WhatsAppService().enviar_mensagem_texto(telefone, mensagem)
        SessaoWhatsapp.objects.filter(telefone=telefone).update(
            etapa="inicial",
            dados_temp={},
        )
    except Exception:
        logger.exception(
            "[PAP_WORKER] Falha ao avisar usuário sobre erro definitivo do job %s",
            job.id,
        )


def _executar_handler(job: PapJobFila) -> None:
    from crm_app.whatsapp_webhook_handler import (
        _executar_analise_credito_background,
        _executar_consulta_pedido_background,
        _executar_consulta_status_online_background,
    )

    handlers = {
        "status_online": lambda p: _executar_consulta_status_online_background(
            p["telefone"],
            p["cpf"],
            p.get("os_filtro"),
            p.get("run_id"),
        ),
        "analise_credito": lambda p: _executar_analise_credito_background(
            p["telefone"],
            p["usuario_id"],
            p["documento"],
            p.get("cpf_representante"),
        ),
        "consulta_pedido": lambda p: _executar_consulta_pedido_background(
            p["telefone"],
            p["usuario_id"],
            p["cpf"],
        ),
    }
    handler = handlers.get(job.tipo)
    if not handler:
        raise ValueError(f"Tipo de job PAP desconhecido: {job.tipo}")
    handler(job.payload or {})


def _persistir_status_job(
    job: PapJobFila,
    *,
    status: str,
    erro: str = "",
    concluir: bool = False,
) -> None:
    """
    Persiste status com reconexão.

    Após Playwright longo a conexão costuma estar morta; sem retry o worker crasha.
    """

    def _save() -> None:
        force_close_db_connections()
        job.status = status
        job.erro = (erro or "")[:4000]
        fields = ["status", "erro"]
        if concluir:
            job.concluido_em = timezone.now()
            fields.append("concluido_em")
        job.save(update_fields=fields)

    try:
        retry_on_db_connection_error(
            _save,
            retries=3,
            label=f"pap_job_{job.id}_status={status}",
        )
    except Exception:
        # Último recurso: UPDATE via QuerySet (evita estado stale do instance).
        logger.exception(
            "[PAP_WORKER] Save do job %s falhou; tentando update direto",
            job.id,
        )
        force_close_db_connections()
        update_kwargs: dict = {"status": status, "erro": (erro or "")[:4000]}
        if concluir:
            update_kwargs["concluido_em"] = timezone.now()
        PapJobFila.objects.filter(pk=job.id).update(**update_kwargs)


def processar_job(job: PapJobFila) -> bool:
    """Executa um job e atualiza status. Retorna True se concluído."""
    force_close_db_connections()
    try:
        logger.info("[PAP_WORKER] Processando job %s tipo=%s", job.id, job.tipo)
        _executar_handler(job)
        _persistir_status_job(
            job,
            status=PapJobFila.STATUS_CONCLUIDO,
            erro="",
            concluir=True,
        )
        return True
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[PAP_WORKER] Erro job %s: %s", job.id, exc)
        # Erro de conexão no meio do handler: não reprocessar cegamente se já
        # esgotou tentativas; mas reconectar para gravar o status.
        if is_db_connection_lost(exc):
            force_close_db_connections()
        erro_txt = f"{exc}\n{tb}"
        try:
            if job.tentativas < job.max_tentativas:
                _persistir_status_job(
                    job,
                    status=PapJobFila.STATUS_PENDENTE,
                    erro=erro_txt,
                    concluir=False,
                )
                return False
            _persistir_status_job(
                job,
                status=PapJobFila.STATUS_ERRO,
                erro=erro_txt,
                concluir=True,
            )
            _notificar_falha_definitiva(job)
        except Exception:
            # Nunca deixar falha de persistência derrubar o processo do worker.
            logger.exception(
                "[PAP_WORKER] Não foi possível persistir status do job %s",
                job.id,
            )
        return False
    finally:
        force_close_db_connections()
