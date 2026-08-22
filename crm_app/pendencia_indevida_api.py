"""API: pendência indevida na esteira."""
import logging
from datetime import datetime
from io import BytesIO

import openpyxl
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PendenciaIndevidaRegistro, Venda
from .pendencia_indevida_utils import registrar_pendencia_indevida
from .utils import is_member

logger = logging.getLogger(__name__)

PERFIS_ESTEIRA = ['Diretoria', 'Admin', 'BackOffice', 'Supervisor']


class PendenciaIndevidaRegistrarView(APIView):
    """POST multipart após venda em PENDÊNCIA: registra metadado e envia ao GC."""
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, PERFIS_ESTEIRA):
            return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

        venda_id = request.data.get('venda_id')
        if not venda_id:
            return Response({'detail': 'venda_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            venda = Venda.objects.select_related('cliente', 'vendedor').get(pk=int(venda_id))
        except (Venda.DoesNotExist, TypeError, ValueError):
            return Response({'detail': 'Venda não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        tem_evidencia = str(request.data.get('tem_evidencia', '')).lower() in ('1', 'true', 'sim', 'yes')
        observacao = (request.data.get('observacao') or '')[:4000]
        motivo_id = request.data.get('motivo_pendencia_id') or request.data.get('motivo_pendencia')
        arquivos = request.FILES.getlist('anexos') or request.FILES.getlist('anexos[]')

        registro, sucesso, msg = registrar_pendencia_indevida(
            usuario=request.user,
            venda=venda,
            motivo_pendencia=int(motivo_id) if motivo_id else None,
            observacao=observacao,
            tem_evidencia=tem_evidencia,
            arquivos_upload=arquivos,
        )
        if registro is None:
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'success': sucesso,
            'detail': msg,
            'id': registro.id,
            'enviado_gc': registro.enviado_gc,
            'erros': registro.erros,
        })


class PendenciaIndevidaRelatorioView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, PERFIS_ESTEIRA):
            return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

        di = (request.query_params.get('data_inicio') or '').strip()
        df = (request.query_params.get('data_fim') or '').strip()
        try:
            d_ini = datetime.strptime(di, '%Y-%m-%d').date() if di else timezone.localdate()
            d_fim = datetime.strptime(df, '%Y-%m-%d').date() if df else timezone.localdate()
        except ValueError:
            return Response({'detail': 'Datas inválidas (use AAAA-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)
        if d_ini > d_fim:
            d_ini, d_fim = d_fim, d_ini

        qs = PendenciaIndevidaRegistro.objects.filter(
            criado_em__date__gte=d_ini,
            criado_em__date__lte=d_fim,
        ).select_related(
            'venda', 'venda__cliente', 'venda__vendedor', 'usuario', 'motivo_pendencia',
        ).prefetch_related('anexos').order_by('criado_em')

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Pendências indevidas'
        ws.append([
            'Data/Hora', 'Venda ID', 'O.S.', 'Cliente', 'Vendedor', 'Motivo pendência',
            'Observação', 'Usuário', 'Teve evidência', 'Enviado GC', 'Arquivos', 'Erros',
        ])
        for r in qs:
            v = r.venda
            anexos = ', '.join(
                (a.nome_original or '') for a in r.anexos.all()
            )
            ws.append([
                r.criado_em.strftime('%d/%m/%Y %H:%M') if r.criado_em else '',
                v.id if v else '',
                (v.ordem_servico or '') if v else '',
                (v.cliente.nome_razao_social if v and v.cliente else ''),
                ((v.vendedor.get_full_name() or v.vendedor.username) if v and v.vendedor else ''),
                (r.motivo_pendencia.nome if r.motivo_pendencia else ''),
                r.observacao or '',
                (r.usuario.get_full_name() or r.usuario.username) if r.usuario else '',
                'Sim' if r.tem_evidencia else 'Não',
                'Sim' if r.enviado_gc else 'Não',
                anexos,
                '; '.join(r.erros) if r.erros else '',
            ])

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"pendencias_indevidas_{d_ini.strftime('%Y%m%d')}_{d_fim.strftime('%Y%m%d')}.xlsx"
        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
