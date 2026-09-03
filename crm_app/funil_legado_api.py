# crm_app/funil_legado_api.py
"""API do Funil: montar planilha legado PAP × OSAB (sem gravar vendas)."""
from __future__ import annotations

import base64
import logging

from django.conf import settings
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.legado_pap_osab import (
    MAX_OSAB_FILES,
    cruzar_pap_osab,
    default_parceiro_por_marca,
    ler_excel_bytes,
    montar_xlsx,
    pick_sheet,
    validar_upload,
)
from crm_app.utils import is_member

logger = logging.getLogger(__name__)


def _marca_site() -> str:
    return (
        getattr(settings, "SITE_BRAND", "")
        or getattr(settings, "SITE_BRAND_NAME", "")
        or ""
    )


def _defaults() -> tuple[str, str]:
    parceiro = (getattr(settings, "LEGADO_OSAB_PARCEIRO", "") or "").strip()
    pdv = (getattr(settings, "LEGADO_OSAB_PDV_SAP", "") or "").strip()
    if parceiro:
        return parceiro, pdv
    inf_p, inf_pdv = default_parceiro_por_marca(_marca_site())
    return inf_p, pdv or inf_pdv


class FunilMontarLegadoConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)
        parceiro, pdv = _defaults()
        return Response(
            {
                "parceiro": parceiro,
                "pdv_sap": pdv,
                "grava_venda": False,
                "max_osab_files": MAX_OSAB_FILES,
                "somente_instalada_padrao": True,
                "proximo_passo": "/importar-legado/",
            }
        )


class FunilMontarLegadoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not is_member(request.user, ["Diretoria", "Admin"]):
            return Response({"detail": "Sem permissão."}, status=403)

        pap_file = request.FILES.get("pap") or request.FILES.get("pap_file")
        if not pap_file:
            return Response({"error": "Envie o arquivo PAP no campo 'pap'."}, status=400)

        osab_files = request.FILES.getlist("osab") or request.FILES.getlist("osab_files")
        if not osab_files:
            unico = request.FILES.get("osab") or request.FILES.get("osab_file")
            osab_files = [unico] if unico else []
        if not osab_files:
            return Response({"error": "Envie ao menos uma OSAB no campo 'osab'."}, status=400)
        if len(osab_files) > MAX_OSAB_FILES:
            return Response({"error": f"No máximo {MAX_OSAB_FILES} arquivos OSAB."}, status=400)

        def_parceiro, def_pdv = _defaults()
        parceiro = (request.data.get("parceiro") or def_parceiro or "").strip()
        pdv_sap = (request.data.get("pdv_sap") or def_pdv or "").strip()
        somente = str(request.data.get("somente_instalada") or "true").strip().lower() in {
            "1",
            "true",
            "sim",
            "on",
            "yes",
        }

        try:
            validar_upload(pap_file.name, pap_file.size or 0)
            pap_bytes = pap_file.read()
            pap_sheets = ler_excel_bytes(pap_file.name, pap_bytes)
            pap_df = pick_sheet(pap_sheets, ("Pedidos", "PEDIDOS", "Pedido", "BASE", "Export"))

            osab_frames = []
            for f in osab_files:
                validar_upload(f.name, f.size or 0)
                content = f.read()
                sheets = ler_excel_bytes(f.name, content)
                osab_frames.append(
                    (f.name, pick_sheet(sheets, ("BASE", "Export", "Exportar")))
                )

            resultado = cruzar_pap_osab(
                pap_df,
                osab_frames,
                parceiro=parceiro,
                pdv_sap=pdv_sap,
                somente_instalada=somente,
            )
            blob = montar_xlsx(resultado)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("Falha ao montar legado PAP×OSAB")
            return Response({"error": "Não foi possível processar os arquivos."}, status=400)

        nome = "Legado_PAP_OSAB.xlsx"
        if resultado["resumo"].get("parceiro"):
            slug = "".join(
                ch if ch.isalnum() else "_"
                for ch in resultado["resumo"]["parceiro"]
            ).strip("_")
            nome = f"Legado_{slug or 'PAP_OSAB'}.xlsx"

        return Response(
            {
                "success": True,
                "grava_venda": False,
                "resumo": resultado["resumo"],
                "nome_arquivo": nome,
                "arquivo_base64": base64.b64encode(blob).decode("ascii"),
                "proximo_passo": "/importar-legado/",
                "aviso": (
                    "Nenhuma venda foi gravada. Revise a planilha e importe "
                    "em Importar Vendas Históricas (Legado)."
                ),
            }
        )
