from rest_framework.views import APIView
from rest_framework.response import Response
from crm_app.models import Venda, HistoricoPapPedido, StatusCRM
import logging

logger = logging.getLogger(__name__)

from rest_framework.permissions import IsAuthenticated

class MigracaoAuditoriaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            if not request.user.is_authenticated:
                return Response({'error': 'Não autorizado'}, status=403)
                
            vendas_auditoria = Venda.objects.filter(
                status_tratamento__isnull=False,
                status_esteira__isnull=True
            ).exclude(
                status_tratamento__estado__iexact='FECHADO'
            ).exclude(pedido_pap__isnull=True).exclude(pedido_pap='')
            
            status_cadastrada = StatusCRM.objects.filter(tipo='Tratamento', nome__iexact='CADASTRADA').first()
            status_agendado = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='AGENDADO').first()
            
            resultados = {
                'processados': 0,
                'avancados_esteira': 0,
                'recusados': 0,
                'nao_encontrado_pap': 0,
                'status_nao_mapeado': 0,
                'detalhes': []
            }
            
            import unicodedata
            def normalize_status(s):
                if not s: return ''
                s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
                return s.upper().strip().replace(' ', '_')

            for venda in vendas_auditoria:
                resultados['processados'] += 1
                hp = HistoricoPapPedido.objects.filter(numero_pedido=venda.pedido_pap).order_by('-capturado_em').first()
                if not hp:
                    resultados['nao_encontrado_pap'] += 1
                    continue
                    
                payload = hp.payload
                if not isinstance(payload, dict):
                    import json
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                        
                status_primario = payload.get('status') or payload.get('statusPrimario') or ''
                status_secundario = payload.get('statusSecundario') or ''
                
                status_primario_norm = normalize_status(status_primario)
                
                if status_primario_norm == 'PEDIDO_GERADO':
                    if status_cadastrada: venda.status_tratamento = status_cadastrada
                    if status_agendado: venda.status_esteira = status_agendado
                    venda.save()
                    resultados['avancados_esteira'] += 1
                    resultados['detalhes'].append(f"Venda {venda.id}: Avançada para CADASTRADA/AGENDADO")
                    
                elif status_primario_norm in ('VENDA_NAO_CONFIRMADA', 'NAO_VENDA'):
                    sec_upper = status_secundario.upper()
                    status_recusa = None
                    
                    # Prioritize exact match
                    status_recusa = StatusCRM.objects.filter(tipo='Tratamento', nome__iexact=status_secundario).first()
                    
                    if not status_recusa:
                        mapped_name = sec_upper
                        if 'DUPLICAD' in sec_upper:
                            mapped_name = 'DUPLICIDADE'
                            
                        status_recusa = StatusCRM.objects.filter(tipo='Tratamento', nome__icontains=mapped_name).first()
                        
                        if not status_recusa:
                            status_recusa = StatusCRM.objects.filter(tipo='Tratamento', nome__icontains=sec_upper.split()[0]).first() if sec_upper else None
                            
                    if status_recusa:
                        venda.status_tratamento = status_recusa
                        venda.save()
                        resultados['recusados'] += 1
                        resultados['detalhes'].append(f"Venda {venda.id}: Recusada com status {status_recusa.nome}")
                    else:
                        resultados['status_nao_mapeado'] += 1
                        if 'status_secundarios_nao_mapeados' not in resultados:
                            resultados['status_secundarios_nao_mapeados'] = []
                        if status_secundario not in resultados['status_secundarios_nao_mapeados']:
                            resultados['status_secundarios_nao_mapeados'].append(status_secundario)
                        resultados['detalhes'].append(f"Venda {venda.id}: Status secundário '{status_secundario}' não encontrado no CRM")
                else:
                    # Verifica se já existe outra venda com o mesmo CPF no sistema
                    outras_vendas = Venda.objects.filter(cliente__cpf_cnpj=venda.cliente.cpf_cnpj).exclude(id=venda.id)
                    if outras_vendas.exists():
                        status_recusa = StatusCRM.objects.filter(tipo='Tratamento', nome__icontains='DUPLICIDADE').first()
                        if status_recusa:
                            venda.status_tratamento = status_recusa
                            venda.save()
                            resultados['recusados'] += 1
                            resultados['detalhes'].append(f"Venda {venda.id}: Recusada por duplicidade de CPF (outro pedido existente)")
                            continue

                    resultados['status_nao_mapeado'] += 1
                    if 'status_primarios_nao_mapeados' not in resultados:
                        resultados['status_primarios_nao_mapeados'] = []
                    if status_primario not in resultados['status_primarios_nao_mapeados']:
                        resultados['status_primarios_nao_mapeados'].append(status_primario)
                    
            return Response(resultados)
        except Exception as e:
            logger.exception("Erro ao sincronizar auditoria")
            return Response({'error': str(e)}, status=500)
