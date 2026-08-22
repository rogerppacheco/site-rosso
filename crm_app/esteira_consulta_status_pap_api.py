"""API para consulta STATUS PAP da aba atual da Esteira (login do usuário)."""
from rest_framework import permissions, status
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import SyncStatusEsteiraExecucao
from crm_app.utils import is_member


class _LenientJSONParser(JSONParser):
    """Body vazio/inválido vira {}."""

    def parse(self, stream, media_type=None, parser_context=None):
        try:
            return super().parse(stream, media_type=media_type, parser_context=parser_context)
        except ParseError:
            return {}


def _pode_consultar(user) -> bool:
    return is_member(user, ['Diretoria', 'BackOffice', 'Admin'])


class ConsultaStatusEsteiraIniciarView(APIView):
    """Inicia consulta PAP dos pedidos da aba/filtros atuais (matrícula do usuário)."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request):
        if not _pode_consultar(request.user):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data if isinstance(request.data, dict) else {}
        colunas_raw = data.get('colunas') if isinstance(data.get('colunas'), dict) else {}
        colunas = {
            str(k): str(v or '').strip()
            for k, v in colunas_raw.items()
            if str(v or '').strip()
        }
        filtros = {
            'aba': (data.get('aba') or '').strip(),
            'busca': (data.get('busca') or '').strip(),
            'periodo_agendamento': (data.get('periodo_agendamento') or '').strip(),
            'status_agendamento': (data.get('status_agendamento') or '').strip(),
            'tipo_pendencia': (data.get('tipo_pendencia') or '').strip(),
            'motivo_pendencia': (data.get('motivo_pendencia') or '').strip(),
            'colunas': colunas,
        }

        from crm_app.esteira_consulta_status_pap_service import criar_e_iniciar_consulta_aba

        exec_id, err, total = criar_e_iniciar_consulta_aba(usuario=request.user, filtros=filtros)
        if err:
            code = status.HTTP_409_CONFLICT
            if 'matrícula' in err.lower() or 'senha' in err.lower():
                code = status.HTTP_400_BAD_REQUEST
            elif 'disponível apenas' in err.lower() or 'nenhum pedido' in err.lower():
                code = status.HTTP_400_BAD_REQUEST
            return Response({'detail': err}, status=code)
        return Response(
            {
                'execucao_id': exec_id,
                'status': 'em_andamento',
                'total_pedidos': total,
                'modo': SyncStatusEsteiraExecucao.MODO_CONSULTA_ABA,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ConsultaStatusEsteiraCancelarView(APIView):
    """Cancela consulta em andamento e desloga a sessão PAP."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request):
        if not _pode_consultar(request.user):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.esteira_consulta_status_pap_service import cancelar_consulta_aba
        from crm_app.esteira_sync_status_pap_service import execucao_em_andamento

        execucao = execucao_em_andamento()
        exec_id = request.data.get('execucao_id') if isinstance(request.data, dict) else None
        exec_id = exec_id or (execucao.id if execucao else None)
        if not exec_id:
            return Response(
                {'detail': 'Nenhuma consulta/sincronização em andamento.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        ok, err = cancelar_consulta_aba(int(exec_id), usuario=request.user)
        if not ok:
            return Response({'detail': err}, status=status.HTTP_409_CONFLICT)
        return Response({'execucao_id': exec_id, 'status': 'interrompido'})


class ConsultaStatusEsteiraStatusView(APIView):
    """Status da execução em andamento ou da última consulta_aba."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ['Diretoria', 'BackOffice', 'Admin', 'Supervisor']):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.esteira_sync_status_pap_api import _serializar_execucao
        from crm_app.esteira_sync_status_pap_service import execucao_em_andamento

        em_andamento = execucao_em_andamento()
        if em_andamento:
            return Response(_serializar_consulta_execucao(em_andamento, em_andamento=True))

        ultima = (
            SyncStatusEsteiraExecucao.objects.filter(
                modo=SyncStatusEsteiraExecucao.MODO_CONSULTA_ABA
            )
            .order_by('-iniciado_em')
            .first()
        )
        if not ultima:
            return Response({'em_andamento': False, 'ultima': None})
        return Response(
            {
                'em_andamento': False,
                'ultima': _serializar_consulta_execucao(ultima, em_andamento=False),
            }
        )


def _serializar_consulta_execucao(execucao, *, em_andamento: bool) -> dict:
    from crm_app.esteira_sync_status_pap_api import _serializar_execucao

    data = _serializar_execucao(execucao, em_andamento=em_andamento)
    rj = execucao.relatorio_json or {}
    data['progresso'] = {
        'atual_venda_id': rj.get('atual_venda_id'),
        'atual_os': rj.get('atual_os') or '',
        'atual_fase': rj.get('atual_fase') or '',
        'ultimos': rj.get('ultimos') or [],
        'filtros': rj.get('filtros') or {},
        'matricula': rj.get('matricula') or '',
    }
    return data
