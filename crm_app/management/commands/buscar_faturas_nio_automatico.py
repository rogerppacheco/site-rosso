# crm_app/management/commands/buscar_faturas_nio_automatico.py

from django.core.management.base import BaseCommand
from datetime import date
from crm_app.models import ContratoM10, FaturaM10
from crm_app.services_nio import buscar_fatura_nio_por_cpf
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Busca automaticamente faturas disponíveis no Nio Negocia'

    def add_arguments(self, parser):
        parser.add_argument(
            '--safra',
            type=str,
            help='Safra específica no formato YYYY-MM (opcional)',
        )
        parser.add_argument(
            '--safra-id',
            type=int,
            help='ID da safra específica (opcional)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Executa sem salvar dados (apenas simula)',
        )

    def handle(self, *args, **options):
        safra = options.get('safra')
        safra_id = options.get('safra_id')
        dry_run = options.get('dry_run')
        
        hoje = date.today()
        
        self.stdout.write(self.style.SUCCESS(f'\n🔄 Iniciando busca automática de faturas - {hoje.strftime("%d/%m/%Y %H:%M")}'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  Modo DRY-RUN ativado - nenhum dado será salvo\n'))
        
        # Filtrar contratos
        query = ContratoM10.objects.filter(status_contrato='ATIVO')
        
        if safra_id:
            query = query.filter(safra_id=safra_id)
            self.stdout.write(f'📁 Filtrando por Safra ID: {safra_id}')
        elif safra:
            query = query.filter(safra=safra)
            self.stdout.write(f'📁 Filtrando por Safra: {safra}')
        else:
            self.stdout.write('📁 Processando todas as safras ativas')
        
        contratos = query.select_related('vendedor')
        total_contratos = contratos.count()
        
        if total_contratos == 0:
            self.stdout.write(self.style.WARNING('⚠️  Nenhum contrato ativo encontrado'))
            return
        
        self.stdout.write(f'📊 Total de contratos a processar: {total_contratos}\n')
        
        # Contadores
        stats = {
            'processados': 0,
            'sucesso': 0,
            'erros': 0,
            'nao_disponiveis': 0,
            'sem_cpf': 0,
            'sem_faturas_pendentes': 0,
        }
        
        # Lista detalhada de erros
        erros_detalhados = []
        
        for idx, contrato in enumerate(contratos, 1):
            self.stdout.write(f'\n[{idx}/{total_contratos}] {contrato.numero_contrato} - {contrato.cliente_nome}')
            
            if not contrato.cpf_cliente:
                self.stdout.write(self.style.WARNING('  ⚠️  CPF não cadastrado'))
                stats['sem_cpf'] += 1
                continue
            
            # Buscar faturas pendentes
            faturas_pendentes = FaturaM10.objects.filter(
                contrato=contrato,
                status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
            ).order_by('numero_fatura')
            
            if not faturas_pendentes.exists():
                self.stdout.write(self.style.SUCCESS('  ✅ Todas as faturas pagas'))
                stats['sem_faturas_pendentes'] += 1
                continue
            
            self.stdout.write(f'  📋 {faturas_pendentes.count()} fatura(s) pendente(s)')
            
            # Processar cada fatura pendente
            for fatura in faturas_pendentes:
                stats['processados'] += 1
                
                # Verificar disponibilidade
                if fatura.data_disponibilidade and fatura.data_disponibilidade > hoje:
                    dias_faltam = (fatura.data_disponibilidade - hoje).days
                    self.stdout.write(
                        self.style.WARNING(
                            f'  ⏳ Fatura {fatura.numero_fatura}: Disponível em {dias_faltam} dia(s) ({fatura.data_disponibilidade.strftime("%d/%m/%Y")})'
                        )
                    )
                    stats['nao_disponiveis'] += 1
                    continue
                
                # Buscar no Nio
                try:
                    self.stdout.write(f'  🔍 Fatura {fatura.numero_fatura}: Buscando no Nio...')
                    dados = buscar_fatura_nio_por_cpf(contrato.cpf_cliente)
                    
                    if dados and not dados.get('sem_dividas'):
                        if not dry_run:
                            # Atualizar fatura
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
                            
                            fatura.save()
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✅ Fatura {fatura.numero_fatura}: R$ {dados.get("valor", 0):.2f} - Venc: {dados.get("data_vencimento", "N/A")}'
                            )
                        )
                        stats['sucesso'] += 1
                    else:
                        mensagem = dados.get('mensagem', 'Sem dados disponíveis') if dados else 'Erro ao buscar'
                        self.stdout.write(self.style.WARNING(f'  ⚠️  Fatura {fatura.numero_fatura}: {mensagem}'))
                        stats['erros'] += 1
                        erros_detalhados.append({
                            'contrato': contrato.numero_contrato,
                            'cliente': contrato.cliente_nome,
                            'fatura': fatura.numero_fatura,
                            'cpf': contrato.cpf_cliente,
                            'erro': mensagem,
                            'tipo': 'sem_dados'
                        })
                
                except Exception as e:
                    erro_msg = str(e)
                    self.stdout.write(self.style.ERROR(f'  ❌ Fatura {fatura.numero_fatura}: Erro - {erro_msg}'))
                    stats['erros'] += 1
                    erros_detalhados.append({
                        'contrato': contrato.numero_contrato,
                        'cliente': contrato.cliente_nome,
                        'fatura': fatura.numero_fatura,
                        'cpf': contrato.cpf_cliente,
                        'erro': erro_msg,
                        'tipo': 'exception'
                    })
                    logger.error(f'Erro ao buscar fatura {fatura.numero_fatura} do contrato {contrato.numero_contrato}: {e}')
        
        # Resumo final
        self.stdout.write('\n' + '='*80)
        self.stdout.write(self.style.SUCCESS('\n📊 RESUMO DA EXECUÇÃO\n'))
        self.stdout.write(f'  Total de contratos: {total_contratos}')
        self.stdout.write(f'  Faturas processadas: {stats["processados"]}')
        self.stdout.write(self.style.SUCCESS(f'  ✅ Sucesso: {stats["sucesso"]}'))
        self.stdout.write(self.style.WARNING(f'  ⏳ Não disponíveis: {stats["nao_disponiveis"]}'))
        self.stdout.write(self.style.ERROR(f'  ❌ Erros: {stats["erros"]}'))
        self.stdout.write(f'  ℹ️  Sem CPF: {stats["sem_cpf"]}')
        self.stdout.write(f'  ℹ️  Sem faturas pendentes: {stats["sem_faturas_pendentes"]}')
        self.stdout.write('\n' + '='*80 + '\n')
        
        # Exibir erros detalhados se houver
        if erros_detalhados:
            self.stdout.write(self.style.ERROR('\n❌ ERROS DETALHADOS:\n'))
            for erro in erros_detalhados:
                self.stdout.write(f'  - Contrato: {erro["contrato"]} | Cliente: {erro["cliente"]}')
                self.stdout.write(f'    Fatura: {erro["fatura"]} | CPF: {erro["cpf"]}')
                self.stdout.write(f'    Tipo: {erro["tipo"]} | Erro: {erro["erro"]}')
                self.stdout.write('')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  Modo DRY-RUN - nenhum dado foi salvo'))
