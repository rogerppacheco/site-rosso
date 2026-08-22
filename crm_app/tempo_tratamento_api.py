"""API do tempo de tratamento: sessões (iniciar/ping/encerrar) e relatório.

As sessões são o cronômetro server-side usado pela auditoria e pela esteira.
O relatório expõe as métricas do dia para o painel e permite disparo manual
do envio via WhatsApp à diretoria.
"""
import logging
from datetime import datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import SessaoTratamento, Venda
from .services import relatorio_tratamento_service as relatorio_svc
from .services import tempo_tratamento_service as tt_svc
from .utils import is_member
from crm_app.perfis_acesso import is_somente_leitura

logger = logging.getLogger(__name__)

GRUPOS_TRATAMENTO = ['Diretoria', 'Admin', 'BackOffice', 'Supervisor', 'Auditoria', 'Qualidade', 'Gerente de Contas']
GRUPOS_RELATORIO = ['Diretoria', 'Admin', 'Supervisor']

MOTIVOS_FRONTEND = {
    'ABANDONO': SessaoTratamento.MOTIVO_ABANDONO,
    'SALVO': SessaoTratamento.MOTIVO_SALVO,
    'LIBERADO': SessaoTratamento.MOTIVO_LIBERADO,
}


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def iniciar_sessao_view(request):
    """Abre uma sessão de tratamento para (venda, usuário, módulo)."""
    if is_somente_leitura(request.user):
        return Response({'detail': 'Perfil somente leitura.'}, status=status.HTTP_403_FORBIDDEN)
    if not is_member(request.user, GRUPOS_TRATAMENTO):
        return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

    venda_id = request.data.get('venda_id')
    modulo = tt_svc.normalizar_modulo(request.data.get('modulo'))
    if not venda_id:
        return Response({'detail': 'venda_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

    venda = get_object_or_404(Venda, pk=venda_id)
    sessao = tt_svc.iniciar_sessao(venda, request.user, modulo)
    return Response({'sessao_id': sessao.id, 'modulo': sessao.modulo, 'iniciado_em': sessao.iniciado_em})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def ping_sessao_view(request):
    """Heartbeat: mantém viva a sessão aberta mais recente do usuário."""
    if is_somente_leitura(request.user):
        return Response({'detail': 'Perfil somente leitura.'}, status=status.HTTP_403_FORBIDDEN)
    venda_id = request.data.get('venda_id')
    modulo = tt_svc.normalizar_modulo(request.data.get('modulo'))
    if not venda_id:
        return Response({'detail': 'venda_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

    sessao = tt_svc.registrar_ping(venda_id, request.user, modulo)
    return Response({'ok': sessao is not None, 'sessao_id': sessao.id if sessao else None})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def encerrar_sessao_view(request):
    """Encerra a sessão do usuário (ex.: saída da tela). Idempotente."""
    if is_somente_leitura(request.user):
        return Response({'detail': 'Perfil somente leitura.'}, status=status.HTTP_403_FORBIDDEN)
    venda_id = request.data.get('venda_id')
    modulo = tt_svc.normalizar_modulo(request.data.get('modulo'))
    motivo = MOTIVOS_FRONTEND.get(
        str(request.data.get('motivo', '')).upper(), SessaoTratamento.MOTIVO_ABANDONO
    )
    if not venda_id:
        return Response({'detail': 'venda_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

    encerradas = tt_svc.encerrar_sessoes(venda_id, request.user, modulo, motivo)
    return Response({'encerradas': encerradas})


def _parse_data(valor: str | None):
    if not valor:
        return timezone.localtime(timezone.now()).date()
    try:
        return datetime.strptime(valor.strip(), '%Y-%m-%d').date()
    except (ValueError, AttributeError):
        return timezone.localtime(timezone.now()).date()


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def relatorio_tratamento_view(request):
    """Métricas do dia para o painel visual (não envia WhatsApp).

    Leitura liberada aos grupos que operam auditoria/esteira. O envio via
    WhatsApp continua restrito à diretoria/admin/supervisor.
    """
    if not is_member(request.user, GRUPOS_TRATAMENTO):
        return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

    data_ref = _parse_data(request.query_params.get('data'))
    modulo = (request.query_params.get('modulo') or '').strip().upper() or None
    if modulo and modulo not in (
        SessaoTratamento.MODULO_AUDITORIA,
        SessaoTratamento.MODULO_ESTEIRA,
    ):
        return Response({'detail': 'Módulo inválido.'}, status=status.HTTP_400_BAD_REQUEST)

    resultado = relatorio_svc.gerar_relatorio(data_ref=data_ref)
    metricas = resultado['metricas']
    if modulo:
        dados_mod = (metricas.get('modulos') or {}).get(modulo) or {
            'linhas': [], 'qtd': 0, 'media': 0, 'mediana': 0, 'outliers': 0,
        }
        metricas = {
            'data_ref': metricas.get('data_ref'),
            'modulos': {modulo: dados_mod},
            'total_geral': {
                'qtd': dados_mod.get('qtd', 0),
                'media': dados_mod.get('media', 0),
                'mediana': dados_mod.get('mediana', 0),
            },
        }
    return Response({
        'data_ref': data_ref.strftime('%Y-%m-%d'),
        'modulo': modulo,
        'metricas': metricas,
        'mensagem': resultado['mensagem'],
        'pode_enviar_whatsapp': is_member(request.user, GRUPOS_RELATORIO),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def enviar_relatorio_tratamento_view(request):
    """Dispara manualmente o relatório do dia para a diretoria via WhatsApp."""
    if not is_member(request.user, GRUPOS_RELATORIO):
        return Response({'detail': 'Permissão negada.'}, status=status.HTTP_403_FORBIDDEN)

    data_ref = _parse_data(request.data.get('data'))
    ok, detalhe = relatorio_svc.enviar_relatorio(data_ref=data_ref)
    http_status = status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST
    return Response({'success': ok, 'detail': detalhe}, status=http_status)
