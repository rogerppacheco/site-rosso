"""
Views para dashboard de análise de buscas de faturas
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Avg, Count, Sum, Q, F
from django.db.models.functions import TruncDate
from datetime import datetime, timedelta
from crm_app.models import HistoricoBuscaFatura, FaturaM10


class AnaliseBuscasView(APIView):
    """Dashboard completo de análise de buscas"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Filtros
        dias = int(request.GET.get('dias', 30))
        tipo_busca = request.GET.get('tipo_busca', '')
        safra = request.GET.get('safra', '')
        
        data_inicial = datetime.now() - timedelta(days=dias)
        
        # Query base
        query = HistoricoBuscaFatura.objects.filter(inicio_em__gte=data_inicial)
        
        if tipo_busca:
            query = query.filter(tipo_busca=tipo_busca)
        if safra:
            query = query.filter(safra=safra)
        
        # Estatísticas gerais
        stats = query.aggregate(
            total_execucoes=Count('id'),
            total_faturas=Sum('total_faturas'),
            total_sucesso=Sum('faturas_sucesso'),
            total_erros=Sum('faturas_erro'),
            tempo_medio=Avg('duracao_segundos'),
            tempo_total=Sum('duracao_segundos')
        )
        
        # Calcular taxa de sucesso
        taxa_sucesso = 0
        if stats['total_faturas'] and stats['total_faturas'] > 0:
            taxa_sucesso = (stats['total_sucesso'] / stats['total_faturas']) * 100
        
        # Histórico das últimas execuções
        execucoes_recentes = query.order_by('-inicio_em')[:20].values(
            'id',
            'tipo_busca',
            'safra',
            'inicio_em',
            'duracao_segundos',
            'total_contratos',
            'total_faturas',
            'faturas_sucesso',
            'faturas_erro',
            'faturas_nao_disponiveis',
            'faturas_retry',
            'status',
            'tempo_medio_fatura'
        )
        
        # Performance por dia
        performance_diaria = query.annotate(
            dia=TruncDate('inicio_em')
        ).values('dia').annotate(
            execucoes=Count('id'),
            faturas_processadas=Sum('total_faturas'),
            sucesso=Sum('faturas_sucesso'),
            erros=Sum('faturas_erro'),
            tempo_total=Sum('duracao_segundos')
        ).order_by('dia')
        
        # Estatísticas por tipo de busca
        por_tipo = query.values('tipo_busca').annotate(
            quantidade=Count('id'),
            faturas=Sum('total_faturas'),
            sucesso=Sum('faturas_sucesso'),
            erros=Sum('faturas_erro'),
            tempo_medio=Avg('duracao_segundos')
        )
        
        # Análise de faturas atuais
        hoje = datetime.now().date()
        faturas_stats = {
            'total': FaturaM10.objects.count(),
            'com_dados': FaturaM10.objects.filter(
                Q(codigo_pix__isnull=False) | Q(codigo_barras__isnull=False)
            ).count(),
            'status_busca': FaturaM10.objects.values('status_busca').annotate(
                count=Count('id')
            ),
            'origem_busca': FaturaM10.objects.exclude(
                origem_busca__isnull=True
            ).values('origem_busca').annotate(
                count=Count('id')
            ),
            'tentativas': FaturaM10.objects.values('tentativas_busca').annotate(
                count=Count('id')
            ).order_by('tentativas_busca'),
        }
        
        # Top 10 faturas mais lentas
        faturas_lentas = FaturaM10.objects.filter(
            tempo_busca_segundos__isnull=False
        ).order_by('-tempo_busca_segundos')[:10].values(
            'id',
            'contrato__numero_contrato',
            'numero_fatura',
            'tempo_busca_segundos',
            'status_busca',
            'tentativas_busca'
        )
        
        # Faturas com erro persistente (3+ tentativas)
        faturas_problema = FaturaM10.objects.filter(
            status_busca='ERRO',
            tentativas_busca__gte=3
        ).select_related('contrato').values(
            'id',
            'contrato__numero_contrato',
            'contrato__cliente_nome',
            'numero_fatura',
            'tentativas_busca',
            'erro_busca',
            'ultima_busca_em'
        )[:50]
        
        return Response({
            'estatisticas_gerais': {
                **stats,
                'taxa_sucesso': round(taxa_sucesso, 2),
                'periodo_dias': dias
            },
            'execucoes_recentes': list(execucoes_recentes),
            'performance_diaria': list(performance_diaria),
            'por_tipo_busca': list(por_tipo),
            'faturas_stats': faturas_stats,
            'faturas_lentas': list(faturas_lentas),
            'faturas_problema': list(faturas_problema)
        })


class MetricasTempoRealView(APIView):
    """Métricas em tempo real para atualização do dashboard"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Última execução
        ultima_execucao = HistoricoBuscaFatura.objects.filter(
            tipo_busca='AUTOMATICA'
        ).order_by('-inicio_em').first()
        
        # Execução em andamento
        em_andamento = HistoricoBuscaFatura.objects.filter(
            status='EM_ANDAMENTO'
        ).first()
        
        # Faturas pendentes de busca
        faturas_pendentes = FaturaM10.objects.filter(
            status_busca='PENDENTE',
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
        ).count()
        
        # Faturas com erro
        faturas_erro = FaturaM10.objects.filter(
            status_busca='ERRO',
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
        ).count()
        
        resultado = {
            'em_andamento': None,
            'ultima_execucao': None,
            'faturas_pendentes': faturas_pendentes,
            'faturas_erro': faturas_erro,
            'proxima_execucao': '00:05'  # Horário agendado
        }
        
        if em_andamento:
            duracao_atual = (datetime.now() - em_andamento.inicio_em).total_seconds()
            resultado['em_andamento'] = {
                'id': em_andamento.id,
                'tipo': em_andamento.tipo_busca,
                'inicio': em_andamento.inicio_em,
                'duracao_atual': round(duracao_atual, 2),
                'faturas_processadas': em_andamento.total_faturas,
                'faturas_sucesso': em_andamento.faturas_sucesso
            }
        
        if ultima_execucao:
            resultado['ultima_execucao'] = {
                'id': ultima_execucao.id,
                'tipo': ultima_execucao.tipo_busca,
                'inicio': ultima_execucao.inicio_em,
                'termino': ultima_execucao.termino_em,
                'duracao': ultima_execucao.duracao_segundos,
                'status': ultima_execucao.status,
                'total_faturas': ultima_execucao.total_faturas,
                'sucesso': ultima_execucao.faturas_sucesso,
                'erros': ultima_execucao.faturas_erro
            }
        
        return Response(resultado)
