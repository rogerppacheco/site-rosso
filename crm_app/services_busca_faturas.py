# Função utilitária para busca de fatura via CPF/ID (usada pelo WhatsApp)
def buscar_fatura_nio(cliente_id):
    from crm_app.services_nio import buscar_fatura_nio_por_cpf
    return buscar_fatura_nio_por_cpf(cliente_id)
"""
Serviço de busca de faturas com rastreamento, métricas e retry automático
"""
import time
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional
from django.db import transaction
from django.utils import timezone
from crm_app.models import FaturaM10, HistoricoBuscaFatura, ContratoM10
from crm_app.services_nio import buscar_fatura_nio_por_cpf, buscar_todas_faturas_nio_por_cpf
import logging

logger = logging.getLogger(__name__)


class BuscaFaturaService:
    """Serviço centralizado para busca de faturas com métricas e retry"""
    
    def __init__(self, tipo_busca: str, safra: Optional[str] = None, usuario=None):
        self.tipo_busca = tipo_busca
        self.safra = safra
        self.usuario = usuario
        self.historico = None
        self.tempos_execucao = []
        self.erros = []
        
    def iniciar_historico(self) -> HistoricoBuscaFatura:
        """Cria registro de histórico"""
        self.historico = HistoricoBuscaFatura.objects.create(
            tipo_busca=self.tipo_busca,
            safra=self.safra,
            usuario=self.usuario,
            status='EM_ANDAMENTO'
        )
        return self.historico
    
    def finalizar_historico(self, status: str = 'CONCLUIDA', mensagem: str = None):
        """Finaliza registro de histórico com estatísticas"""
        if not self.historico:
            return
        
        self.historico.termino_em = timezone.now()
        self.historico.duracao_segundos = (
            self.historico.termino_em - self.historico.inicio_em
        ).total_seconds()
        self.historico.status = status
        self.historico.mensagem = mensagem
        
        # Calcular métricas de performance
        if self.tempos_execucao:
            self.historico.tempo_medio_fatura = sum(self.tempos_execucao) / len(self.tempos_execucao)
            self.historico.tempo_min_fatura = min(self.tempos_execucao)
            self.historico.tempo_max_fatura = max(self.tempos_execucao)
        
        self.historico.save()
    
    def buscar_fatura_individual(self, fatura: FaturaM10, origem: str = 'INDIVIDUAL') -> Dict:
        """
        Busca uma fatura individual com rastreamento completo
        
        Returns:
            Dict com: {
                'sucesso': bool,
                'dados': dict ou None,
                'tempo': float,
                'erro': str ou None
            }
        """
        inicio = time.time()
        resultado = {
            'sucesso': False,
            'dados': None,
            'tempo': 0,
            'erro': None
        }
        
        try:
            # Incrementar tentativas
            fatura.tentativas_busca += 1
            fatura.origem_busca = origem
            fatura.ultima_busca_em = timezone.now()
            
            # Buscar no Nio
            cpf = fatura.contrato.cpf_cliente
            dados = buscar_fatura_nio_por_cpf(cpf, incluir_pdf=False)
            
            tempo_decorrido = time.time() - inicio
            fatura.tempo_busca_segundos = Decimal(str(tempo_decorrido))
            self.tempos_execucao.append(tempo_decorrido)
            
            if dados and not dados.get('sem_dividas'):
                # Sucesso - atualizar fatura
                if dados.get('valor'):
                    fatura.valor = dados['valor']
                if dados.get('data_vencimento'):
                    fatura.data_vencimento = dados['data_vencimento']
                if dados.get('codigo_pix'):
                    fatura.codigo_pix = dados['codigo_pix']
                if dados.get('codigo_barras'):
                    fatura.codigo_barras = dados['codigo_barras']
                if dados.get('pdf_url'):
                    fatura.pdf_url = dados['pdf_url']
                
                fatura.status_busca = 'SUCESSO'
                fatura.erro_busca = None
                
                resultado['sucesso'] = True
                resultado['dados'] = dados
            else:
                # Sem dados disponíveis
                mensagem_erro = dados.get('mensagem', 'Sem dados disponíveis') if dados else 'Erro na API'
                fatura.status_busca = 'ERRO'
                fatura.erro_busca = mensagem_erro
                resultado['erro'] = mensagem_erro
            
            resultado['tempo'] = tempo_decorrido
            fatura.save()
            
        except Exception as e:
            tempo_decorrido = time.time() - inicio
            erro_msg = str(e)
            
            fatura.status_busca = 'ERRO'
            fatura.erro_busca = erro_msg
            fatura.tempo_busca_segundos = Decimal(str(tempo_decorrido))
            fatura.save()
            
            resultado['erro'] = erro_msg
            resultado['tempo'] = tempo_decorrido
            
            logger.error(f"Erro ao buscar fatura {fatura.id}: {e}")
        
        return resultado
    
    def buscar_faturas_contrato(self, contrato: ContratoM10, origem: str = 'SAFRA') -> Dict:
        """
        Busca todas as faturas disponíveis de um contrato com matching por vencimento
        
        Returns:
            Dict com estatísticas da busca
        """
        stats = {
            'processadas': 0,
            'sucesso': 0,
            'erro': 0,
            'nao_disponiveis': 0,
        }
        
        if not contrato.cpf_cliente:
            return stats
        
        hoje = date.today()
        
        # Buscar faturas pendentes disponíveis
        faturas = FaturaM10.objects.filter(
            contrato=contrato,
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
        ).filter(
            models.Q(data_disponibilidade__isnull=True) | 
            models.Q(data_disponibilidade__lte=hoje)
        ).order_by('numero_fatura')
        
        if not faturas.exists():
            return stats
        
        try:
            # Buscar todas as faturas no Nio de uma vez
            faturas_nio = buscar_todas_faturas_nio_por_cpf(contrato.cpf_cliente, incluir_pdf=False)
            
            if not faturas_nio:
                # Marcar todas como erro
                for fatura in faturas:
                    fatura.tentativas_busca += 1
                    fatura.origem_busca = origem
                    fatura.ultima_busca_em = timezone.now()
                    fatura.status_busca = 'ERRO'
                    fatura.erro_busca = 'Nenhuma fatura retornada pela API'
                    fatura.save()
                    stats['erro'] += 1
                    stats['processadas'] += 1
                return stats
            
            # Fazer matching por vencimento
            for fatura in faturas:
                inicio = time.time()
                stats['processadas'] += 1
                
                fatura.tentativas_busca += 1
                fatura.origem_busca = origem
                fatura.ultima_busca_em = timezone.now()
                
                # Verificar disponibilidade
                if fatura.data_disponibilidade and fatura.data_disponibilidade > hoje:
                    fatura.status_busca = 'PENDENTE'
                    fatura.erro_busca = f'Disponível em {fatura.data_disponibilidade}'
                    fatura.save()
                    stats['nao_disponiveis'] += 1
                    continue
                
                # Encontrar melhor match por vencimento
                melhor_match = None
                menor_diff = 999
                
                for fatura_nio in faturas_nio:
                    if fatura_nio.get('data_vencimento') and fatura.data_vencimento:
                        diff_dias = abs((fatura.data_vencimento - fatura_nio['data_vencimento']).days)
                        if diff_dias <= 3 and diff_dias < menor_diff:
                            menor_diff = diff_dias
                            melhor_match = fatura_nio
                
                tempo_decorrido = time.time() - inicio
                fatura.tempo_busca_segundos = Decimal(str(tempo_decorrido))
                self.tempos_execucao.append(tempo_decorrido)
                
                if melhor_match:
                    # Atualizar com dados do Nio
                    if melhor_match.get('valor'):
                        fatura.valor = melhor_match['valor']
                    if melhor_match.get('data_vencimento'):
                        fatura.data_vencimento = melhor_match['data_vencimento']
                    if melhor_match.get('codigo_pix'):
                        fatura.codigo_pix = melhor_match['codigo_pix']
                    if melhor_match.get('codigo_barras'):
                        fatura.codigo_barras = melhor_match['codigo_barras']
                    if melhor_match.get('pdf_url'):
                        fatura.pdf_url = melhor_match['pdf_url']
                    
                    fatura.status_busca = 'SUCESSO'
                    fatura.erro_busca = None
                    stats['sucesso'] += 1
                else:
                    fatura.status_busca = 'ERRO'
                    fatura.erro_busca = 'Sem match de vencimento com faturas Nio'
                    stats['erro'] += 1
                
                fatura.save()
        
        except Exception as e:
            logger.error(f"Erro ao buscar faturas do contrato {contrato.numero_contrato}: {e}")
            # Marcar todas como erro
            for fatura in faturas:
                fatura.tentativas_busca += 1
                fatura.origem_busca = origem
                fatura.ultima_busca_em = timezone.now()
                fatura.status_busca = 'ERRO'
                fatura.erro_busca = str(e)
                fatura.save()
                stats['erro'] += 1
                if stats['processadas'] < faturas.count():
                    stats['processadas'] += 1
        
        return stats
    
    def retry_erros(self, max_tentativas: int = 3) -> Dict:
        """
        Retry automático de faturas com erro
        
        Args:
            max_tentativas: Número máximo de tentativas antes de desistir
        
        Returns:
            Dict com estatísticas do retry
        """
        stats = {
            'total': 0,
            'sucesso': 0,
            'erro': 0,
            'desistencias': 0
        }
        
        # Buscar faturas com erro e poucas tentativas
        faturas_erro = FaturaM10.objects.filter(
            status_busca='ERRO',
            tentativas_busca__lt=max_tentativas,
            status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
        ).select_related('contrato')
        
        stats['total'] = faturas_erro.count()
        
        if stats['total'] == 0:
            return stats
        
        logger.info(f"🔄 Iniciando retry de {stats['total']} faturas com erro...")
        
        if self.historico:
            self.historico.faturas_retry = stats['total']
            self.historico.save()
        
        for fatura in faturas_erro:
            resultado = self.buscar_fatura_individual(fatura, origem='RETRY')
            
            if resultado['sucesso']:
                stats['sucesso'] += 1
            else:
                stats['erro'] += 1
                
                # Se atingiu max tentativas, marcar como desistência
                if fatura.tentativas_busca >= max_tentativas:
                    stats['desistencias'] += 1
                    logger.warning(
                        f"⚠️ Desistindo de fatura {fatura.id} após {fatura.tentativas_busca} tentativas"
                    )
        
        return stats


# Importar Q para queries complexas
from django.db.models import Q
