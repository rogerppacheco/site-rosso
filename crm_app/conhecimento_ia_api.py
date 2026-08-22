# crm_app/conhecimento_ia_api.py
"""
API para upload e gestão de documentos que alimentam a base de conhecimento da IA (PDF, Excel, PPT).
"""
import logging
import os
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .models import DocumentoConhecimentoIA, UrlConhecimentoIA
from .conhecimento_ia_extract import extrair_texto_arquivo
from .conhecimento_ia_fetch_url import fetch_url, fetch_url_and_crawl

logger = logging.getLogger(__name__)

TIPO_POR_EXT = {
    "pdf": "PDF",
    "xls": "EXCEL",
    "xlsx": "EXCEL",
    "ppt": "PPT",
    "pptx": "PPT",
}


class ConhecimentoIAListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        docs = DocumentoConhecimentoIA.objects.all().order_by("-data_upload")
        return Response({
            "resultados": [
                {
                    "id": d.id,
                    "titulo": d.titulo,
                    "nome_original": d.nome_original,
                    "tipo": d.tipo,
                    "ativo": d.ativo,
                    "tem_conteudo": bool((d.conteudo_extraido or "").strip()),
                    "data_upload": d.data_upload.isoformat() if d.data_upload else None,
                }
                for d in docs
            ]
        })


class ConhecimentoIAUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        arquivo = request.FILES.get("arquivo")
        if not arquivo:
            return Response({"error": "Nenhum arquivo enviado"}, status=400)
        nome = arquivo.name or ""
        ext = os.path.splitext(nome)[-1].lower().lstrip(".")
        if ext not in TIPO_POR_EXT:
            return Response({
                "error": "Tipo não suportado. Use PDF, Excel (xls/xlsx) ou PowerPoint (ppt/pptx)."
            }, status=400)
        if arquivo.size > 50 * 1024 * 1024:  # 50 MB
            return Response({"error": "Arquivo muito grande (máximo 50 MB)"}, status=400)

        titulo = (request.data.get("titulo") or "").strip() or nome
        doc = DocumentoConhecimentoIA.objects.create(
            titulo=titulo,
            arquivo=arquivo,
            nome_original=nome,
            tipo=TIPO_POR_EXT.get(ext, "OUTRO"),
            usuario=request.user,
        )
        # Extrair texto
        try:
            arquivo.seek(0)
            texto = extrair_texto_arquivo(arquivo)
            if texto:
                doc.conteudo_extraido = texto[:500000]  # limite 500k chars
                doc.save(update_fields=["conteudo_extraido"])
        except Exception as e:
            logger.warning("[Conhecimento IA] Erro ao extrair texto: %s", e)

        return Response({
            "sucesso": True,
            "id": doc.id,
            "titulo": doc.titulo,
            "tipo": doc.tipo,
            "tem_conteudo": bool((doc.conteudo_extraido or "").strip()),
        })


class ConhecimentoIADeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, doc_id):
        try:
            doc = DocumentoConhecimentoIA.objects.get(pk=doc_id)
            if doc.arquivo:
                try:
                    doc.arquivo.delete(save=False)
                except Exception:
                    pass
            doc.delete()
            return Response({"sucesso": True})
        except DocumentoConhecimentoIA.DoesNotExist:
            return Response({"error": "Documento não encontrado"}, status=404)


class ConhecimentoIAToggleAtivoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, doc_id):
        try:
            doc = DocumentoConhecimentoIA.objects.get(pk=doc_id)
            doc.ativo = not doc.ativo
            doc.save(update_fields=["ativo"])
            return Response({"sucesso": True, "ativo": doc.ativo})
        except DocumentoConhecimentoIA.DoesNotExist:
            return Response({"error": "Documento não encontrado"}, status=404)


class ConhecimentoIAReprocessarView(APIView):
    """Reextrai o texto do arquivo (útil se a extração falhou)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, doc_id):
        try:
            doc = DocumentoConhecimentoIA.objects.get(pk=doc_id)
            if not doc.arquivo:
                return Response({"error": "Arquivo não encontrado"}, status=400)
            path = doc.arquivo.path
            texto = extrair_texto_arquivo(path)
            doc.conteudo_extraido = (texto or "")[:500000]
            doc.save(update_fields=["conteudo_extraido"])
            return Response({
                "sucesso": True,
                "tem_conteudo": bool((doc.conteudo_extraido or "").strip()),
            })
        except DocumentoConhecimentoIA.DoesNotExist:
            return Response({"error": "Documento não encontrado"}, status=404)
        except Exception as e:
            logger.warning("[Conhecimento IA] Reprocessar falhou: %s", e)
            return Response({"error": str(e)}, status=500)


# --- URLs de sites (conteúdo extraído para a IA) ---


class ConhecimentoIAUrlListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        urls = UrlConhecimentoIA.objects.all().order_by("-data_upload")
        return Response({
            "resultados": [
                {
                    "id": u.id,
                    "url": u.url,
                    "titulo": u.titulo,
                    "ativo": u.ativo,
                    "tem_conteudo": bool((u.conteudo_extraido or "").strip()),
                    "data_upload": u.data_upload.isoformat() if u.data_upload else None,
                }
                for u in urls
            ]
        })


class ConhecimentoIAUrlAddView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        url = (request.data.get("url") or "").strip()
        if not url:
            return Response({"error": "Informe a URL"}, status=400)
        crawlar_site = request.data.get("crawlar_site") in (True, "true", "1")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            if crawlar_site:
                texto, titulo = fetch_url_and_crawl(url)
            else:
                texto = fetch_url(url)
                titulo = ""
            titulo = (titulo or url)[:255]
            if not texto:
                return Response({
                    "error": "Não foi possível extrair texto da página. Verifique a URL ou tente 'Crawlar site'."
                }, status=400)
            obj = UrlConhecimentoIA.objects.create(
                url=url,
                titulo=titulo or url[:255],
                conteudo_extraido=texto[:500000],
                usuario=request.user,
            )
            return Response({
                "sucesso": True,
                "id": obj.id,
                "titulo": obj.titulo,
                "tem_conteudo": True,
            })
        except Exception as e:
            logger.warning("[Conhecimento IA] Erro ao adicionar URL: %s", e)
            return Response({"error": str(e)}, status=500)


class ConhecimentoIAUrlDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, url_id):
        try:
            UrlConhecimentoIA.objects.get(pk=url_id).delete()
            return Response({"sucesso": True})
        except UrlConhecimentoIA.DoesNotExist:
            return Response({"error": "URL não encontrada"}, status=404)


class ConhecimentoIAUrlToggleAtivoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, url_id):
        try:
            u = UrlConhecimentoIA.objects.get(pk=url_id)
            u.ativo = not u.ativo
            u.save(update_fields=["ativo"])
            return Response({"sucesso": True, "ativo": u.ativo})
        except UrlConhecimentoIA.DoesNotExist:
            return Response({"error": "URL não encontrada"}, status=404)


class ConhecimentoIAUrlReprocessarView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, url_id):
        try:
            u = UrlConhecimentoIA.objects.get(pk=url_id)
            crawlar_site = request.data.get("crawlar_site") in (True, "true", "1")
            if crawlar_site:
                texto, titulo = fetch_url_and_crawl(u.url)
            else:
                texto = fetch_url(u.url)
                titulo = u.titulo
            if texto:
                u.conteudo_extraido = texto[:500000]
                if titulo:
                    u.titulo = titulo[:255]
                u.save(update_fields=["conteudo_extraido", "titulo"])
            return Response({
                "sucesso": True,
                "tem_conteudo": bool((u.conteudo_extraido or "").strip()),
            })
        except UrlConhecimentoIA.DoesNotExist:
            return Response({"error": "URL não encontrada"}, status=404)
        except Exception as e:
            logger.warning("[Conhecimento IA] Reprocessar URL falhou: %s", e)
            return Response({"error": str(e)}, status=500)
