"""
Endpoints de saúde para probe do Railway e monitoramento interno.
"""
from __future__ import annotations

import io
import os
import time
from typing import Any

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


def _memoria_mb() -> float | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        # Linux: ru_maxrss em KB; macOS em bytes
        rss = usage.ru_maxrss
        if rss > 10_000_000:
            return round(rss / (1024 * 1024), 1)
        return round(rss / 1024, 1)
    except Exception:
        return None


class HealthView(View):
    """Liveness: processo HTTP responde (sem banco)."""

    def get(self, request: HttpRequest) -> JsonResponse:
        payload: dict[str, Any] = {
            "status": "ok",
            "service": os.environ.get("RAILWAY_SERVICE_NAME")
            or getattr(settings, "SITE_BRAND", "site-record"),
        }
        return JsonResponse(payload)


class ReadyView(View):
    """Readiness: PostgreSQL acessível."""

    def get(self, request: HttpRequest) -> JsonResponse:
        t0 = time.monotonic()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            db_ms = round((time.monotonic() - t0) * 1000, 1)
            return JsonResponse({"status": "ok", "database": "up", "db_latency_ms": db_ms})
        except Exception as exc:
            return JsonResponse(
                {"status": "error", "database": "down", "detail": str(exc)[:200]},
                status=503,
            )


class MetricsView(View):
    """Métricas leves para diagnóstico interno (sem autenticação — não expõe dados sensíveis)."""

    def get(self, request: HttpRequest) -> JsonResponse:
        pap_queue_pending = 0
        pap_queue_running = 0
        webhook_queue_pending = 0
        webhook_queue_running = 0
        try:
            from crm_app.pap_job_fila import PapJobFila

            pap_queue_pending = PapJobFila.objects.filter(status=PapJobFila.STATUS_PENDENTE).count()
            pap_queue_running = PapJobFila.objects.filter(status=PapJobFila.STATUS_PROCESSANDO).count()
        except Exception:
            pass
        try:
            from crm_app.whatsapp_webhook_fila import WhatsappWebhookFila

            webhook_queue_pending = WhatsappWebhookFila.objects.filter(
                status=WhatsappWebhookFila.STATUS_PENDENTE
            ).count()
            webhook_queue_running = WhatsappWebhookFila.objects.filter(
                status=WhatsappWebhookFila.STATUS_PROCESSANDO
            ).count()
        except Exception:
            pass

        cache_ok = False
        try:
            from django.core.cache import cache

            probe_key = "_metrics_probe"
            cache.set(probe_key, "1", 10)
            cache_ok = cache.get(probe_key) == "1"
        except Exception:
            cache_ok = False

        worker_mode = "web"
        if getattr(settings, "PAP_WORKER_MODE", False):
            worker_mode = "pap"
        elif getattr(settings, "WHATSAPP_WORKER_MODE", False):
            worker_mode = "webhook"
        elif getattr(settings, "RUN_SCHEDULER", False):
            worker_mode = "scheduler"

        return JsonResponse(
            {
                "status": "ok",
                "worker_mode": worker_mode,
                "pap_dedicated_worker": getattr(settings, "PAP_USE_DEDICATED_WORKER", False),
                "whatsapp_dedicated_worker": getattr(settings, "WHATSAPP_USE_DEDICATED_WORKER", False),
                "pap_queue_pending": pap_queue_pending,
                "pap_queue_running": pap_queue_running,
                "webhook_queue_pending": webhook_queue_pending,
                "webhook_queue_running": webhook_queue_running,
                "cache_ok": cache_ok,
                "memory_mb": _memoria_mb(),
                "gunicorn_workers": int(getattr(settings, "GUNICORN_WORKERS", 1)),
                "pid": os.getpid(),
            }
        )

@method_decorator(csrf_exempt, name='dispatch')
class ManutencaoView(View):
    """Endpoint de manutenção para rodar management commands no servidor.
    Protegido pelo SECRET_KEY via header X-Manutencao-Token.
    """

    def post(self, request: HttpRequest) -> JsonResponse:
        token_esperado = settings.SECRET_KEY
        token_recebido = request.headers.get('X-Manutencao-Token', '')
        if token_recebido != token_esperado:
            return JsonResponse({'error': 'Forbidden'}, status=403)

        comando = request.POST.get('comando') or ''
        comandos_permitidos = ['corrigir_tipo_venda_pap']
        if comando not in comandos_permitidos:
            return JsonResponse(
                {'error': f'Comando não permitido. Permitidos: {comandos_permitidos}'},
                status=400
            )

        try:
            from django.core.management import call_command
            buf = io.StringIO()
            call_command(comando, stdout=buf, stderr=buf)
            output = buf.getvalue()
            return JsonResponse({'success': True, 'output': output})
        except Exception as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=500)
