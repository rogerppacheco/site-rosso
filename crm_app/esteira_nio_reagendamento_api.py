"""API Esteira — reagendamento automático via bot WhatsApp Nio (7029)."""
from rest_framework import permissions, status
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import NioReagendamentoExecucao
from crm_app.utils import is_member


class _LenientJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        try:
            return super().parse(stream, media_type=media_type, parser_context=parser_context)
        except ParseError:
            return {}


def _pode_executar(user) -> bool:
    return is_member(user, ['Diretoria', 'BackOffice', 'Admin'])


class NioReagendamentoUnitarioView(APIView):
    """Dispara reagendamento Nio para um pedido 7029 CLIENTE."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request, venda_id: int):
        if not _pode_executar(request.user):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.services.nio_reagendamento_whatsapp_service import criar_e_iniciar_unitario

        exec_id, err = criar_e_iniciar_unitario(venda_id=venda_id, usuario=request.user)
        if err:
            code = status.HTTP_409_CONFLICT
            if 'não encontrada' in err.lower() or 'não é' in err.lower() or 'sem' in err.lower():
                code = status.HTTP_400_BAD_REQUEST
            return Response({'detail': err}, status=code)
        return Response(
            {'execucao_id': exec_id, 'status': 'em_andamento', 'venda_id': venda_id},
            status=status.HTTP_202_ACCEPTED,
        )


class NioReagendamentoIniciarView(APIView):
    """Inicia reagendamento em massa (7029 CLIENTE) da aba/filtros atuais."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request):
        if not _pode_executar(request.user):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data if isinstance(request.data, dict) else {}
        colunas_raw = data.get('colunas') if isinstance(data.get('colunas'), dict) else {}
        colunas = {str(k): str(v or '').strip() for k, v in colunas_raw.items() if str(v or '').strip()}
        filtros = {
            'aba': (data.get('aba') or '').strip(),
            'busca': (data.get('busca') or '').strip(),
            'periodo_agendamento': (data.get('periodo_agendamento') or '').strip(),
            'status_agendamento': (data.get('status_agendamento') or '').strip(),
            'tipo_pendencia': (data.get('tipo_pendencia') or '').strip(),
            'motivo_pendencia': (data.get('motivo_pendencia') or '').strip(),
            'colunas': colunas,
        }

        from crm_app.services.nio_reagendamento_whatsapp_service import criar_e_iniciar_massa

        exec_id, err, total = criar_e_iniciar_massa(filtros=filtros, usuario=request.user)
        if err:
            code = status.HTTP_409_CONFLICT
            if 'nenhum pedido' in err.lower() or 'desabilitado' in err.lower():
                code = status.HTTP_400_BAD_REQUEST
            return Response({'detail': err}, status=code)
        return Response(
            {
                'execucao_id': exec_id,
                'status': 'em_andamento',
                'total_pedidos': total,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class NioReagendamentoCancelarView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request):
        if not _pode_executar(request.user):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.services.nio_reagendamento_whatsapp_service import cancelar_execucao, execucao_em_andamento

        execucao = execucao_em_andamento()
        exec_id = request.data.get('execucao_id') if isinstance(request.data, dict) else None
        exec_id = exec_id or (execucao.id if execucao else None)
        if not exec_id:
            return Response({'detail': 'Nenhum reagendamento Nio em andamento.'}, status=status.HTTP_404_NOT_FOUND)
        ok, err = cancelar_execucao(int(exec_id), usuario=request.user)
        if not ok:
            return Response({'detail': err}, status=status.HTTP_409_CONFLICT)
        return Response({'execucao_id': exec_id, 'status': 'cancelando'})


class NioReagendamentoStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ['Diretoria', 'BackOffice', 'Admin', 'Supervisor']):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.services.nio_reagendamento_whatsapp_service import execucao_em_andamento, serializar_execucao

        em_andamento = execucao_em_andamento()
        if em_andamento:
            return Response(serializar_execucao(em_andamento, em_andamento=True))

        ultima = NioReagendamentoExecucao.objects.order_by('-iniciado_em').first()
        if not ultima:
            return Response({'em_andamento': False, 'ultima': None})
        return Response({
            'em_andamento': False,
            'ultima': serializar_execucao(ultima, em_andamento=False),
        })
