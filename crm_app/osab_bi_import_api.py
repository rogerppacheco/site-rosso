"""API para disparar manualmente a importação OSAB via BI do PAP."""
from __future__ import annotations

import logging
import threading

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.utils import is_member

logger = logging.getLogger(__name__)


class ImportarOsabBiPapManualView(APIView):
    """
    POST: inicia em background o export do Power BI (Dinâmica OSAB) + import CRM.
    GET: indica se há conta robô IMPORT_OSAB_BI ativa e se alguma está em uso.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin", "BackOffice"]):
            return Response({"detail": "Sem permissão."}, status=403)
        from usuarios.models import CredencialRoboPAP

        qs = CredencialRoboPAP.objects.filter(funcao="IMPORT_OSAB_BI", ativo=True).order_by("id")
        contas = [
            {
                "id": c.id,
                "matricula": c.matricula,
                "em_uso": bool(c.em_uso),
            }
            for c in qs
        ]
        return Response(
            {
                "disponivel": len(contas) > 0,
                "em_andamento": any(c["em_uso"] for c in contas),
                "contas": contas,
            }
        )

    def post(self, request):
        if not is_member(request.user, ["Diretoria", "Admin", "BackOffice"]):
            return Response({"detail": "Sem permissão."}, status=403)

        from usuarios.models import CredencialRoboPAP

        matricula = (request.data.get("matricula") or "").strip()
        enviar_whatsapp = str(request.data.get("enviar_whatsapp", "false")).lower() in (
            "1",
            "true",
            "yes",
            "sim",
        )

        qs = CredencialRoboPAP.objects.filter(funcao="IMPORT_OSAB_BI", ativo=True)
        if matricula:
            qs = qs.filter(matricula__iexact=matricula)
        robo = qs.order_by("id").first()
        if not robo:
            return Response(
                {
                    "ok": False,
                    "detail": (
                        "Cadastre uma Conta de Serviço PAP com função "
                        "«Importação OSAB (BI Dinâmica)» em Governança."
                    ),
                },
                status=400,
            )
        if robo.em_uso:
            return Response(
                {
                    "ok": False,
                    "detail": f"A conta {robo.matricula} já está em uso. Aguarde o término.",
                },
                status=409,
            )

        def _run():
            try:
                from crm_app.services.import_osab_bi_pap_service import (
                    exportar_e_importar_osab_bi,
                )

                res = exportar_e_importar_osab_bi(
                    matricula=robo.matricula,
                    headless=True,
                    enviar_whatsapp=enviar_whatsapp,
                )
                logger.info(
                    "[OSAB BI MANUAL] ok=%s matricula=%s log_id=%s detail=%s",
                    res.ok,
                    res.matricula,
                    res.log_id,
                    res.detail,
                )
            except Exception:
                logger.exception("[OSAB BI MANUAL] Falha no job em background")

        threading.Thread(target=_run, daemon=True, name="osab-bi-manual").start()
        return Response(
            {
                "ok": True,
                "detail": (
                    f"Importação via BI iniciada com a conta {robo.matricula}. "
                    "Acompanhe o histórico abaixo em alguns minutos."
                ),
                "matricula": robo.matricula,
            },
            status=202,
        )
