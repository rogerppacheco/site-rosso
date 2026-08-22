"""API Gestão Aproveitamento na Esteira de Vendas (Fase 1 — KPIs com dados atuais)."""

from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.esteira_eventos_utils import TIPO_AGENDAMENTO, TIPO_MOTIVO_PENDENCIA, TIPO_STATUS_ESTEIRA
from crm_app.models import LembreteInstalacaoEnviado, PendenciaIndevidaRegistro, Venda, VendaEsteiraEvento
from crm_app.utils import is_member

GRUPOS_GESTAO_APROVEITAMENTO_ESTEIRA = ['Diretoria', 'BackOffice', 'Admin']


def _montar_resumo_mes(vendas_qs, inicio_mes, fim_mes):
    from crm_app.views import _filtro_data_efetiva_instalacao_intervalo_venda

    filtro_abertura = Q(data_abertura__date__gte=inicio_mes) & Q(data_abertura__date__lte=fim_mes)
    filtro_inst_mes = _filtro_data_efetiva_instalacao_intervalo_venda(inicio_mes, fim_mes)
    filtro_inst = Q(status_esteira__nome__iexact='INSTALADA')

    cohort = vendas_qs.filter(filtro_abertura)
    total = cohort.count()

    # Instaladas no mês: data efetiva no período (independente do mês de abertura da O.S.)
    instaladas = vendas_qs.filter(filtro_inst).filter(filtro_inst_mes).count()

    # Aproveitamento: instaladas no mês ÷ O.S. abertas no mês (mesma regra do Painel de Performance)
    pend = cohort.filter(status_esteira__nome__icontains='PENDEN').count()
    agend = cohort.filter(status_esteira__nome__iexact='AGENDADO').count()
    canc = cohort.filter(status_esteira__nome__icontains='CANCELAD').count()
    aprov = round((instaladas / total * 100.0), 2) if total > 0 else 0.0
    return {
        'total_abertas': total,
        'instaladas': instaladas,
        'aproveitamento': aprov,
        'pendentes': pend,
        'agendadas': agend,
        'canceladas': canc,
    }


def _agregar_pendencias_por_motivo(vendas_qs):
    rows = (
        vendas_qs.filter(
            status_esteira__nome__icontains='PENDEN',
            motivo_pendencia__isnull=False,
        )
        .values('motivo_pendencia__tipo_pendencia', 'motivo_pendencia__nome')
        .annotate(qtd=Count('id'))
        .order_by('-qtd', 'motivo_pendencia__tipo_pendencia', 'motivo_pendencia__nome')
    )
    return [
        {
            'tipo': r['motivo_pendencia__tipo_pendencia'] or '—',
            'motivo': r['motivo_pendencia__nome'] or '—',
            'qtd': r['qtd'],
        }
        for r in rows
    ]


def _agregar_por_vendedor(users_qs, inicio_mes, fim_mes):
    from crm_app.views import _perf_filtro_data_efetiva_instalacao_intervalo

    filtro_os = (
        Q(vendas__ativo=True)
        & ~Q(vendas__ordem_servico='')
        & Q(vendas__ordem_servico__isnull=False)
        & Q(vendas__status_tratamento__nome__iexact='CADASTRADA')
    )
    filtro_abertura = (
        Q(vendas__data_abertura__date__gte=inicio_mes)
        & Q(vendas__data_abertura__date__lte=fim_mes)
    )
    filtro_inst = Q(vendas__status_esteira__nome__iexact='INSTALADA')
    filtro_inst_mes = _perf_filtro_data_efetiva_instalacao_intervalo(inicio_mes, fim_mes)

    qs = users_qs.annotate(
        total=Count('vendas', filter=filtro_os & filtro_abertura),
        instaladas=Count('vendas', filter=filtro_os & filtro_inst_mes & filtro_inst),
        pend=Count(
            'vendas',
            filter=filtro_os & filtro_abertura & Q(vendas__status_esteira__nome__icontains='PENDEN'),
        ),
        agend=Count(
            'vendas',
            filter=filtro_os & filtro_abertura & Q(vendas__status_esteira__nome__iexact='AGENDADO'),
        ),
        canc=Count(
            'vendas',
            filter=filtro_os & filtro_abertura & Q(vendas__status_esteira__nome__icontains='CANCELAD'),
        ),
    ).values(
        'id', 'username', 'cluster', 'total', 'instaladas', 'pend', 'agend', 'canc',
    ).order_by('username')

    lista = []
    for u in qs:
        tot = int(u['total'] or 0)
        inst = int(u['instaladas'] or 0)
        lista.append({
            'vendedor_id': u['id'],
            'vendedor': (u['username'] or '').upper(),
            'cluster': u.get('cluster') or '-',
            'total': tot,
            'instaladas': inst,
            'aproveitamento': round((inst / tot * 100.0), 2) if tot > 0 else 0.0,
            'pend': int(u['pend'] or 0),
            'agend': int(u['agend'] or 0),
            'canc': int(u['canc'] or 0),
        })
    return lista


def _periodo_datetime(inicio_mes, fim_mes):
    ini_dt = timezone.make_aware(datetime.combine(inicio_mes, datetime.min.time()))
    fim_dt = timezone.make_aware(datetime.combine(fim_mes, datetime.max.time()))
    return ini_dt, fim_dt


def _metricas_eventos_esteira(user_ids, inicio_mes, fim_mes):
    """KPIs derivados da timeline de eventos (Fase 2)."""
    if not user_ids:
        return {
            'entradas_pendencia': 0,
            'os_com_2_ou_mais_pendencias': 0,
            'reagendamentos': 0,
            'pendencias_por_motivo_historico': [],
            'tem_dados': False,
        }

    ini_dt, fim_dt = _periodo_datetime(inicio_mes, fim_mes)
    base = VendaEsteiraEvento.objects.filter(
        venda__vendedor_id__in=user_ids,
        venda__ativo=True,
        criado_em__gte=ini_dt,
        criado_em__lte=fim_dt,
    )

    if not base.exists():
        return {
            'entradas_pendencia': 0,
            'os_com_2_ou_mais_pendencias': 0,
            'reagendamentos': 0,
            'pendencias_por_motivo_historico': [],
            'tem_dados': False,
        }

    entradas_pend = base.filter(
        tipo_evento=TIPO_STATUS_ESTEIRA,
        valor_novo__icontains='PENDEN',
    )
    os_recorrentes = entradas_pend.values('venda_id').annotate(n=Count('id')).filter(n__gte=2).count()

    reagendamentos = (
        base.filter(tipo_evento=TIPO_AGENDAMENTO)
        .exclude(valor_novo='')
        .values('venda_id')
        .annotate(n=Count('id'))
        .filter(n__gte=2)
        .count()
    )

    rows_motivo = (
        base.filter(tipo_evento=TIPO_MOTIVO_PENDENCIA)
        .exclude(valor_novo='')
        .values('valor_novo')
        .annotate(qtd=Count('id'))
        .order_by('-qtd', 'valor_novo')[:15]
    )
    pend_hist = [
        {'motivo': r['valor_novo'] or '—', 'qtd': r['qtd']}
        for r in rows_motivo
    ]

    return {
        'entradas_pendencia': entradas_pend.count(),
        'os_com_2_ou_mais_pendencias': os_recorrentes,
        'reagendamentos': reagendamentos,
        'pendencias_por_motivo_historico': pend_hist,
        'tem_dados': True,
    }


def _stats_lembrete(inicio_mes, fim_mes, vendas_qs):
    venda_ids = list(vendas_qs.values_list('id', flat=True))
    if not venda_ids:
        return {'enviados': 0, 'respondidos': 0, 'taxa_resposta': 0.0}
    ini_dt, fim_dt = _periodo_datetime(inicio_mes, fim_mes)
    base = LembreteInstalacaoEnviado.objects.filter(
        venda_id__in=venda_ids,
        data_envio__gte=ini_dt,
        data_envio__lte=fim_dt,
    )
    enviados = base.count()
    respondidos = base.filter(respondido_em__isnull=False).count()
    taxa = round((respondidos / enviados * 100.0), 2) if enviados > 0 else 0.0
    return {'enviados': enviados, 'respondidos': respondidos, 'taxa_resposta': taxa}


class GestaoAproveitamentoEsteiraView(APIView):
    """
    KPIs de aproveitamento e esteira para gestão (Fase 1).
    Reutiliza critérios do Painel de Performance (O.S. cadastrada, data efetiva de instalação).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, GRUPOS_GESTAO_APROVEITAMENTO_ESTEIRA):
            return Response(
                {'detail': 'Acesso restrito à gestão da esteira.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        from crm_app.views import (
            _aplicar_filtro_vendedor_ativo_perf,
            _perf_grupos_gestao,
            _perf_montar_payload_gestao,
            _perf_resolver_periodos_performance,
        )

        User = get_user_model()
        hoje = timezone.localtime(timezone.now()).date()
        periodo = _perf_resolver_periodos_performance(request, request.user, hoje)
        inicio_mes = periodo['inicio_mes']
        fim_mes = periodo['fim_mes']

        users = User.objects.exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])
        grupos_gestao = _perf_grupos_gestao()
        if is_member(request.user, grupos_gestao):
            pass
        elif is_member(request.user, ['Supervisor']):
            users = users.filter(Q(supervisor=request.user) | Q(id=request.user.id))
        else:
            users = users.filter(id=request.user.id)

        filtro_canal = (request.query_params.get('canal') or '').strip()
        if filtro_canal:
            users = users.filter(canal__iexact=filtro_canal)
        filtro_cluster = (request.query_params.get('cluster') or '').strip()
        if filtro_cluster:
            users = users.filter(cluster=filtro_cluster)

        consultor_id = request.query_params.get('consultor_id') or request.query_params.get('vendedor_id')
        if consultor_id:
            try:
                users = users.filter(id=int(consultor_id))
            except (TypeError, ValueError):
                pass

        users = _aplicar_filtro_vendedor_ativo_perf(
            users, request.user, request.query_params.get('vendedor_ativo'),
        )

        user_ids = list(users.values_list('id', flat=True))
        vendas_base = Venda.objects.filter(
            ativo=True,
            vendedor_id__in=user_ids,
        ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='').filter(
            status_tratamento__nome__iexact='CADASTRADA',
        )

        resumo = _montar_resumo_mes(vendas_base, inicio_mes, fim_mes)

        from crm_app.models import StatusCRM

        status_abertos = StatusCRM.objects.filter(
            tipo__iexact='Esteira', estado='ABERTO',
        ).values_list('id', flat=True)
        vendas_pendentes_abertas = vendas_base.filter(
            status_esteira_id__in=status_abertos,
            status_esteira__nome__icontains='PENDEN',
        )
        pend_operacional = _agregar_pendencias_por_motivo(vendas_pendentes_abertas)

        filtro_abertura = Q(data_abertura__date__gte=inicio_mes) & Q(data_abertura__date__lte=fim_mes)
        pend_cohort_mes = _agregar_pendencias_por_motivo(
            vendas_base.filter(filtro_abertura, status_esteira__nome__icontains='PENDEN'),
        )

        ini_dt, fim_dt = _periodo_datetime(inicio_mes, fim_mes)
        pend_indevidas = PendenciaIndevidaRegistro.objects.filter(
            criado_em__gte=ini_dt,
            criado_em__lte=fim_dt,
        )
        if user_ids:
            pend_indevidas = pend_indevidas.filter(
                Q(venda__vendedor_id__in=user_ids) | Q(venda__isnull=True),
            )

        payload = {
            'periodo': {
                'mes_referencia': periodo['mes_referencia'],
                'inicio': inicio_mes.isoformat(),
                'fim': fim_mes.isoformat(),
            },
            'resumo': resumo,
            'por_vendedor': _agregar_por_vendedor(users, inicio_mes, fim_mes),
            'pendencias_operacional': pend_operacional,
            'pendencias_cohort_mes': pend_cohort_mes,
            'pendencias_indevidas': {
                'total': pend_indevidas.count(),
                'com_evidencia': pend_indevidas.filter(tem_evidencia=True).count(),
                'enviadas_gc': pend_indevidas.filter(enviado_gc=True).count(),
            },
            'lembrete_instalacao': _stats_lembrete(inicio_mes, fim_mes, vendas_base),
            'eventos_esteira': _metricas_eventos_esteira(user_ids, inicio_mes, fim_mes),
            'notas': {
                'aproveitamento': (
                    'Instaladas (data efetiva no mês) ÷ O.S. abertas no mês. '
                    'Instaladas inclui vendas de meses anteriores instaladas no período.'
                ),
                'pendencias_operacional': 'Foto atual: pedidos pendentes na esteira (status aberto).',
                'pendencias_cohort_mes': 'O.S. abertas no mês que estão pendentes agora.',
                'eventos_esteira': (
                    'Contagens a partir dos eventos registrados (alterações manuais e OSAB a partir desta versão). '
                    'Dados anteriores não aparecem na timeline.'
                ),
            },
        }

        if request.query_params.get('incluir_gestao') == '1':
            payload['gestao'] = _perf_montar_payload_gestao(users, inicio_mes, request)

        if periodo.get('aviso'):
            payload['aviso'] = periodo['aviso']

        return Response(payload)
