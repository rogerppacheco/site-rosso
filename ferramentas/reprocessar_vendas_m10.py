"""
Script para reprocessar vendas instaladas do passado e criar contratos M-10
Executa a mesma lógica do signal para vendas antigas
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import Venda, ContratoM10, SafraM10
from datetime import datetime

def reprocessar_vendas():
    print("🔄 Iniciando reprocessamento de vendas instaladas...")
    
    # Buscar todas as vendas instaladas ativas com OS
    vendas = Venda.objects.filter(
        ativo=True,
        data_instalacao__isnull=False,
        ordem_servico__isnull=False
    ).exclude(
        ordem_servico=''
    ).select_related('cliente', 'plano', 'vendedor')
    
    total_vendas = vendas.count()
    print(f"📊 Total de vendas instaladas encontradas: {total_vendas}")
    
    criados = 0
    atualizados = 0
    erros = 0
    pulados = 0
    
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
                print(f"  ✏️  Atualizado: OS {venda.ordem_servico}")
                continue
            
            # Encontrar ou criar a SafraM10 do mês da instalação
            mes_referencia = venda.data_instalacao.replace(day=1)
            
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
                print(f"  📅 Criada nova safra: {mes_referencia.strftime('%m/%Y')}")
            
            # Criar o ContratoM10
            numero_contrato = f"{venda.id}-{venda.ordem_servico}"
            
            contrato_m10 = ContratoM10.objects.create(
                numero_contrato=numero_contrato,
                safra=safra_m10,
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
            print(f"  ✅ Criado: OS {venda.ordem_servico} - Cliente: {contrato_m10.cliente_nome}")
            
        except Exception as e:
            erros += 1
            print(f"  ❌ Erro ao processar Venda {venda.id} (OS: {venda.ordem_servico}): {e}")
    
    print("\n" + "="*60)
    print("📊 RESUMO DO REPROCESSAMENTO:")
    print("="*60)
    print(f"✅ Contratos criados:    {criados}")
    print(f"✏️  Contratos atualizados: {atualizados}")
    print(f"⏭️  Pulados (já existiam): {pulados}")
    print(f"❌ Erros:                {erros}")
    print(f"📊 Total processado:     {total_vendas}")
    print("="*60)
    print("✅ Reprocessamento concluído!")

if __name__ == '__main__':
    reprocessar_vendas()
