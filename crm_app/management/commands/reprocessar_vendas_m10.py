"""
Django management command para reprocessar vendas instaladas e criar contratos M-10
Uso: python manage.py reprocessar_vendas_m10
"""
from django.core.management.base import BaseCommand
from crm_app.models import Venda, ContratoM10, SafraM10


class Command(BaseCommand):
    help = 'Reprocessa vendas instaladas do passado e cria contratos M-10'

    def handle(self, *args, **options):
        self.stdout.write("🔄 Iniciando reprocessamento de vendas instaladas...")
        
        # Buscar todas as vendas INSTALADAS ativas com OS
        vendas = Venda.objects.filter(
            ativo=True,
            data_instalacao__isnull=False,
            ordem_servico__isnull=False,
            status_esteira__nome__iexact='INSTALADA'
        ).exclude(
            ordem_servico=''
        ).select_related('cliente', 'plano', 'vendedor', 'status_esteira')
        
        total_vendas = vendas.count()
        self.stdout.write(f"📊 Total de vendas instaladas encontradas: {total_vendas}")
        
        criados = 0
        atualizados = 0
        erros = 0
        
        for venda in vendas:
            try:
                # Verificar se já existe contrato com esta OS
                contrato_existente = ContratoM10.objects.filter(ordem_servico=venda.ordem_servico).first()
                
                if contrato_existente:
                    # Atualizar o contrato existente
                    contrato_existente.venda = venda
                    contrato_existente.cliente_nome = venda.cliente.nome_razao_social if venda.cliente else ''
                    contrato_existente.save()
                    atualizados += 1
                    self.stdout.write(f"  ✏️  Atualizado: OS {venda.ordem_servico}")
                    continue
                
                # Encontrar ou criar a SafraM10 do mês da instalação
                mes_referencia = venda.data_instalacao.replace(day=1)
                safra_str = venda.data_instalacao.strftime('%Y-%m')
                
                safra_m10, created_safra = SafraM10.objects.get_or_create(
                    mes_referencia=mes_referencia,
                    defaults={
                        'total_instalados': 0,
                        'total_ativos': 0,
                        'total_elegivel_bonus': 0,
                        'valor_bonus_total': 0,
                    }
                )
                
                if created_safra:
                    self.stdout.write(f"  📅 Criada nova safra: {mes_referencia.strftime('%m/%Y')}")
                
                # Criar o ContratoM10
                numero_contrato = f"{venda.id}-{venda.ordem_servico}"
                
                contrato_m10 = ContratoM10.objects.create(
                    numero_contrato=numero_contrato,
                    safra=safra_str,  # CharField, não objeto
                    venda=venda,
                    ordem_servico=venda.ordem_servico,
                    cliente_nome=venda.cliente.nome_razao_social if venda.cliente else '',
                    cpf_cliente=venda.cliente.cpf_cnpj if venda.cliente else '',
                    vendedor=venda.vendedor,
                    data_instalacao=venda.data_instalacao,
                    plano_original=venda.plano.nome if venda.plano else 'N/A',
                    plano_atual=venda.plano.nome if venda.plano else 'N/A',
                    valor_plano=venda.plano.valor if venda.plano and hasattr(venda.plano, 'valor') else 0,
                    status_contrato='ATIVO',
                    elegivel_bonus=False,
                )
                
                criados += 1
                self.stdout.write(f"  ✅ Criado: OS {venda.ordem_servico} - Cliente: {contrato_m10.cliente_nome}")
                
            except Exception as e:
                erros += 1
                self.stdout.write(self.style.ERROR(f"  ❌ Erro ao processar Venda {venda.id} (OS: {venda.ordem_servico}): {e}"))
        
        self.stdout.write("\n" + "="*60)
        self.stdout.write(self.style.SUCCESS("📊 RESUMO DO REPROCESSAMENTO:"))
        self.stdout.write("="*60)
        self.stdout.write(self.style.SUCCESS(f"✅ Contratos criados:    {criados}"))
        self.stdout.write(self.style.SUCCESS(f"✏️  Contratos atualizados: {atualizados}"))
        self.stdout.write(self.style.ERROR(f"❌ Erros:                {erros}"))
        self.stdout.write(f"📊 Total processado:     {total_vendas}")
        self.stdout.write("="*60)
        self.stdout.write(self.style.SUCCESS("✅ Reprocessamento concluído!"))
