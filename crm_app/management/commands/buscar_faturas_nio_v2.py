"""
Comando melhorado de busca automática com retry, métricas e rastreamento
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from datetime import date
from crm_app.models import ContratoM10
from crm_app.services_busca_faturas import BuscaFaturaService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Busca automática de faturas com retry e métricas completas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--safra',
            type=str,
            help='Safra específica no formato YYYY-MM (opcional)',
        )
        parser.add_argument(
            '--retry',
            action='store_true',
            help='Executar retry de erros ao final',
        )
        parser.add_argument(
            '--max-tentativas',
            type=int,
            default=3,
            help='Número máximo de tentativas de retry (padrão: 3)',
        )

    def handle(self, *args, **options):
        safra = options.get('safra')
        executar_retry = options.get('retry', True)  # Padrão: sempre fazer retry
        max_tentativas = options.get('max_tentativas', 3)
        
        hoje = date.today()
        inicio_geral = timezone.now()
        
        # Inicializar serviço
        servico = BuscaFaturaService(
            tipo_busca='AUTOMATICA',
            safra=safra,
            usuario=None
        )
        
        historico = servico.iniciar_historico()
        
        self.stdout.write(self.style.SUCCESS(
            f'\n{"="*80}\n'
            f'🤖 BUSCA AUTOMÁTICA DE FATURAS\n'
            f'{"="*80}\n'
        ))
        
        self.stdout.write(f'📅 Data: {hoje.strftime("%d/%m/%Y %H:%M")}')
        self.stdout.write(f'🆔 ID Histórico: {historico.id}\n')
        
        # Filtrar contratos
        query = ContratoM10.objects.filter(status_contrato='ATIVO')
        
        if safra:
            query = query.filter(safra=safra)
            self.stdout.write(f'📁 Filtrando por Safra: {safra}')
        else:
            self.stdout.write('📁 Processando todas as safras ativas')
        
        contratos = query.select_related('vendedor')
        total_contratos = contratos.count()
        
        if total_contratos == 0:
            self.stdout.write(self.style.WARNING('\n⚠️  Nenhum contrato ativo encontrado'))
            servico.finalizar_historico('CONCLUIDA', 'Nenhum contrato para processar')
            return
        
        historico.total_contratos = total_contratos
        historico.save()
        
        self.stdout.write(f'📊 Total de contratos: {total_contratos}\n')
        self.stdout.write('─' * 80 + '\n')
        
        # Estatísticas gerais
        stats = {
            'contratos_processados': 0,
            'faturas_processadas': 0,
            'faturas_sucesso': 0,
            'faturas_erro': 0,
            'faturas_nao_disponiveis': 0,
            'contratos_sem_cpf': 0,
            'contratos_sem_faturas': 0,
        }
        
        # Processar cada contrato
        for idx, contrato in enumerate(contratos, 1):
            porcentagem = (idx / total_contratos) * 100
            self.stdout.write(
                f'\n[{idx}/{total_contratos} - {porcentagem:.1f}%] '
                f'{contrato.numero_contrato} - {contrato.cliente_nome[:40]}'
            )
            
            if not contrato.cpf_cliente:
                self.stdout.write(self.style.WARNING('  ⚠️  CPF não cadastrado'))
                stats['contratos_sem_cpf'] += 1
                continue
            
            stats['contratos_processados'] += 1
            
            # Buscar faturas do contrato
            self.stdout.write(f'  🔍 Processando faturas...')
            resultado = servico.buscar_faturas_contrato(contrato, origem='AUTOMATICA')
            
            # Atualizar estatísticas
            stats['faturas_processadas'] += resultado['processadas']
            stats['faturas_sucesso'] += resultado['sucesso']
            stats['faturas_erro'] += resultado['erro']
            stats['faturas_nao_disponiveis'] += resultado['nao_disponiveis']
            
            if resultado['processadas'] == 0:
                self.stdout.write(self.style.SUCCESS('  ✅ Todas as faturas pagas'))
                stats['contratos_sem_faturas'] += 1
            else:
                # Exibir resumo do contrato
                self.stdout.write(
                    f'  📊 Processadas: {resultado["processadas"]} | '
                    f'✅ Sucesso: {resultado["sucesso"]} | '
                    f'❌ Erro: {resultado["erro"]} | '
                    f'⏳ Não disp.: {resultado["nao_disponiveis"]}'
                )
            
            # Progress visual a cada 10 contratos
            if idx % 10 == 0 or idx == total_contratos:
                tempo_decorrido = (timezone.now() - inicio_geral).total_seconds()
                tempo_medio = tempo_decorrido / idx if idx > 0 else 0
                estimativa_restante = tempo_medio * (total_contratos - idx)
                
                self.stdout.write(
                    f'\n  ⏱️  Tempo: {tempo_decorrido:.1f}s | '
                    f'Média: {tempo_medio:.2f}s/contrato | '
                    f'Estimativa restante: {estimativa_restante:.0f}s'
                )
        
        # Atualizar histórico com estatísticas
        historico.total_faturas = stats['faturas_processadas']
        historico.faturas_sucesso = stats['faturas_sucesso']
        historico.faturas_erro = stats['faturas_erro']
        historico.faturas_nao_disponiveis = stats['faturas_nao_disponiveis']
        historico.save()
        
        # Resumo parcial
        self.stdout.write('\n' + '='*80)
        self.stdout.write(self.style.SUCCESS('\n📊 RESUMO PARCIAL\n'))
        self.stdout.write(f'  Contratos processados: {stats["contratos_processados"]}')
        self.stdout.write(f'  Faturas processadas: {stats["faturas_processadas"]}')
        self.stdout.write(self.style.SUCCESS(f'  ✅ Sucesso: {stats["faturas_sucesso"]}'))
        self.stdout.write(self.style.ERROR(f'  ❌ Erros: {stats["faturas_erro"]}'))
        self.stdout.write(self.style.WARNING(f'  ⏳ Não disponíveis: {stats["faturas_nao_disponiveis"]}'))
        
        # RETRY AUTOMÁTICO DE ERROS
        if executar_retry and stats['faturas_erro'] > 0:
            self.stdout.write('\n' + '='*80)
            self.stdout.write(self.style.WARNING(
                f'\n🔄 RETRY AUTOMÁTICO - {stats["faturas_erro"]} erros detectados\n'
            ))
            self.stdout.write(f'  Tentativas máximas: {max_tentativas}')
            self.stdout.write('─' * 80 + '\n')
            
            retry_stats = servico.retry_erros(max_tentativas=max_tentativas)
            
            self.stdout.write(f'\n  Total de faturas com retry: {retry_stats["total"]}')
            self.stdout.write(self.style.SUCCESS(f'  ✅ Corrigidos: {retry_stats["sucesso"]}'))
            self.stdout.write(self.style.ERROR(f'  ❌ Ainda com erro: {retry_stats["erro"]}'))
            self.stdout.write(self.style.WARNING(f'  ⚠️  Desistências: {retry_stats["desistencias"]}'))
            
            # Atualizar estatísticas finais
            stats['faturas_sucesso'] += retry_stats['sucesso']
            stats['faturas_erro'] = retry_stats['erro']
        
        # RESUMO FINAL
        tempo_total = (timezone.now() - inicio_geral).total_seconds()
        
        self.stdout.write('\n' + '='*80)
        self.stdout.write(self.style.SUCCESS('\n🎯 RESUMO FINAL\n'))
        self.stdout.write('─' * 80)
        
        self.stdout.write(f'\n  📊 Contratos')
        self.stdout.write(f'     • Processados: {stats["contratos_processados"]}')
        self.stdout.write(f'     • Sem CPF: {stats["contratos_sem_cpf"]}')
        self.stdout.write(f'     • Sem faturas pendentes: {stats["contratos_sem_faturas"]}')
        
        self.stdout.write(f'\n  💳 Faturas')
        self.stdout.write(f'     • Total processadas: {stats["faturas_processadas"]}')
        self.stdout.write(self.style.SUCCESS(f'     • ✅ Sucesso: {stats["faturas_sucesso"]}'))
        self.stdout.write(self.style.ERROR(f'     • ❌ Erros: {stats["faturas_erro"]}'))
        self.stdout.write(self.style.WARNING(f'     • ⏳ Não disponíveis: {stats["faturas_nao_disponiveis"]}'))
        
        # Taxa de sucesso
        if stats['faturas_processadas'] > 0:
            taxa_sucesso = (stats['faturas_sucesso'] / stats['faturas_processadas']) * 100
            self.stdout.write(f'\n  📈 Taxa de sucesso: {taxa_sucesso:.1f}%')
        
        # Métricas de performance
        self.stdout.write(f'\n  ⏱️  Performance')
        self.stdout.write(f'     • Tempo total: {tempo_total:.2f}s ({tempo_total/60:.1f} min)')
        if stats['contratos_processados'] > 0:
            self.stdout.write(f'     • Tempo médio/contrato: {tempo_total/stats["contratos_processados"]:.2f}s')
        if stats['faturas_processadas'] > 0:
            self.stdout.write(f'     • Tempo médio/fatura: {tempo_total/stats["faturas_processadas"]:.2f}s')
        
        if servico.tempos_execucao:
            self.stdout.write(f'     • Tempo mínimo: {min(servico.tempos_execucao):.3f}s')
            self.stdout.write(f'     • Tempo máximo: {max(servico.tempos_execucao):.3f}s')
        
        self.stdout.write('\n' + '='*80 + '\n')
        
        # Finalizar histórico
        mensagem_final = (
            f'Processados: {stats["contratos_processados"]} contratos, '
            f'{stats["faturas_processadas"]} faturas. '
            f'Sucesso: {stats["faturas_sucesso"]}, '
            f'Erros: {stats["faturas_erro"]}'
        )
        
        servico.finalizar_historico('CONCLUIDA', mensagem_final)
        
        self.stdout.write(self.style.SUCCESS(
            f'✅ Busca concluída! Histórico ID: {historico.id}\n'
        ))
