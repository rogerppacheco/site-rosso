"""API para sincronização noturna/manual da esteira via PAP."""
from rest_framework import permissions, status
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import SyncStatusEsteiraExecucao
from crm_app.utils import is_member


class _LenientJSONParser(JSONParser):
    """Body vazio/inválido vira {} — iniciar/cancelar não dependem de payload."""

    def parse(self, stream, media_type=None, parser_context=None):
        try:
            return super().parse(stream, media_type=media_type, parser_context=parser_context)
        except ParseError:
            return {}


class SyncStatusEsteiraIniciarView(APIView):
    """Inicia sincronização manual (BackOffice/Diretoria/Admin)."""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request):
        if not is_member(request.user, ['Diretoria', 'BackOffice', 'Admin']):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.esteira_sync_status_pap_service import criar_e_iniciar_execucao_manual

        exec_id, err = criar_e_iniciar_execucao_manual(usuario=request.user)
        if err:
            return Response({'detail': err}, status=status.HTTP_409_CONFLICT)
        return Response({'execucao_id': exec_id, 'status': 'em_andamento'}, status=status.HTTP_202_ACCEPTED)


class SyncStatusEsteiraCancelarView(APIView):
    """Cancela execução em andamento (BackOffice/Diretoria/Admin)."""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [_LenientJSONParser]

    def post(self, request):
        if not is_member(request.user, ['Diretoria', 'BackOffice', 'Admin']):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.esteira_sync_status_pap_service import cancelar_execucao, execucao_em_andamento

        execucao = execucao_em_andamento()
        exec_id = request.data.get('execucao_id') or (execucao.id if execucao else None)
        if not exec_id:
            return Response({'detail': 'Nenhuma sincronização em andamento.'}, status=status.HTTP_404_NOT_FOUND)
        ok, err = cancelar_execucao(int(exec_id), usuario=request.user)
        if not ok:
            return Response({'detail': err}, status=status.HTTP_409_CONFLICT)
        return Response({'execucao_id': exec_id, 'status': 'interrompido'})


class SyncStatusEsteiraStatusView(APIView):
    """Status da execução em andamento ou da última concluída."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ['Diretoria', 'BackOffice', 'Admin', 'Supervisor']):
            return Response({'detail': 'Acesso negado.'}, status=status.HTTP_403_FORBIDDEN)

        from crm_app.esteira_sync_status_pap_service import execucao_em_andamento

        em_andamento = execucao_em_andamento()
        if em_andamento:
            return Response(_serializar_execucao(em_andamento, em_andamento=True))

        ultima = (
            SyncStatusEsteiraExecucao.objects.order_by('-iniciado_em').first()
        )
        if not ultima:
            return Response({'em_andamento': False, 'ultima': None})
        return Response({
            'em_andamento': False,
            'ultima': _serializar_execucao(ultima, em_andamento=False),
        })


def _serializar_execucao(execucao, *, em_andamento: bool) -> dict:
    from crm_app.esteira_sync_status_pap_service import _minutos_sem_progresso, _stale_minutos

    minutos = _minutos_sem_progresso(execucao)
    stale_lim = _stale_minutos()
    return {
        'em_andamento': em_andamento,
        'id': execucao.id,
        'modo': execucao.modo,
        'status': execucao.status,
        'iniciado_em': execucao.iniciado_em.isoformat() if execucao.iniciado_em else None,
        'finalizado_em': execucao.finalizado_em.isoformat() if execucao.finalizado_em else None,
        'total_pedidos': execucao.total_pedidos,
        'processados': execucao.processados,
        'atualizados': execucao.atualizados,
        'sem_alteracao': execucao.sem_alteracao,
        'erros': execucao.erros,
        'ignorados_sem_cpf': execucao.ignorados_sem_cpf,
        'iniciado_por': execucao.iniciado_por.username if execucao.iniciado_por else None,
        'mensagem_erro': execucao.mensagem_erro or '',
        'minutos_sem_progresso': round(minutos, 1) if minutos is not None else None,
        'stale_minutos': stale_lim,
    }
