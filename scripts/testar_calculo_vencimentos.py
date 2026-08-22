# scripts/testar_calculo_vencimentos.py
"""
Script para testar os cálculos de data de vencimento das faturas
"""
import os
import sys
import django
from datetime import date

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, FaturaM10, SafraM10


def testar_calculo_vencimentos():
    """Testa o cálculo de vencimentos para diferentes dias de instalação"""
    
    print("=" * 80)
    print("TESTE DE CÁLCULO DE VENCIMENTOS DAS FATURAS")
    print("=" * 80)
    
    # Criar ou buscar safra de teste
    safra, _ = SafraM10.objects.get_or_create(
        mes_referencia=date(2025, 12, 1),
        defaults={'total_instalados': 0, 'total_ativos': 0}
    )
    
    # Casos de teste
    casos_teste = [
        (1, 'Instalação dia 01 (início do mês)'),
        (4, 'Instalação dia 04'),
        (10, 'Instalação dia 10'),
        (15, 'Instalação dia 15 (meio do mês)'),
        (28, 'Instalação dia 28 (último dia normal)'),
        (29, 'Instalação dia 29 (exceção)'),
        (30, 'Instalação dia 30 (exceção)'),
        (31, 'Instalação dia 31 (exceção)'),
    ]
    
    for dia_instalacao, descricao in casos_teste:
        print(f"\n{'=' * 80}")
        print(f"📅 {descricao}")
        print(f"{'=' * 80}")
        
        data_instalacao = date(2025, 12, dia_instalacao)
        print(f"Data de instalação: {data_instalacao.strftime('%d/%m/%Y')}")
        
        # Criar contrato de teste (será deletado depois)
        contrato = ContratoM10(
            safra=safra,
            numero_contrato=f'TESTE-{dia_instalacao:02d}',
            cliente_nome='Cliente Teste',
            cpf_cliente='12345678900',
            data_instalacao=data_instalacao,
            plano_original='Plano 100MB',
            plano_atual='Plano 100MB',
            valor_plano=100.00,
            status_contrato='ATIVO'
        )
        
        # Calcular vencimentos manualmente (sem salvar no BD)
        vencimento_fatura_1 = contrato.calcular_vencimento_fatura_1()
        data_disponibilidade_1 = contrato.calcular_data_disponibilidade(1)
        
        print(f"\n🔹 Fatura 1:")
        print(f"   Vencimento: {vencimento_fatura_1.strftime('%d/%m/%Y')}")
        print(f"   Disponível a partir de: {data_disponibilidade_1.strftime('%d/%m/%Y')}")
        print(f"   Dias após instalação: {(vencimento_fatura_1 - data_instalacao).days}")
        
        # Mostrar as próximas 3 faturas
        for i in range(2, 5):
            vencimento = contrato.calcular_vencimento_fatura_n(i)
            disponibilidade = contrato.calcular_data_disponibilidade(i)
            print(f"\n🔹 Fatura {i}:")
            print(f"   Vencimento: {vencimento.strftime('%d/%m/%Y')}")
            print(f"   Disponível a partir de: {disponibilidade.strftime('%d/%m/%Y')}")
        
        # Validações
        print(f"\n✅ Validações:")
        
        # Validação 1: Dias entre instalação e vencimento da fatura 1
        dias_diff = (vencimento_fatura_1 - data_instalacao).days
        if dia_instalacao <= 28:
            esperado = 25
            if dias_diff == esperado:
                print(f"   ✓ Diferença de dias correta: {dias_diff} dias (esperado: {esperado})")
            else:
                print(f"   ✗ ERRO: Diferença de dias incorreta: {dias_diff} (esperado: {esperado})")
        else:
            # Para dias 29-31, deve vencer no dia 26 do mês seguinte
            if vencimento_fatura_1.day == 26 and vencimento_fatura_1.month == (data_instalacao.month % 12) + 1:
                print(f"   ✓ Vencimento fixo dia 26 aplicado corretamente")
            else:
                print(f"   ✗ ERRO: Vencimento deveria ser dia 26 do mês seguinte")
        
        # Validação 2: Fatura 2 deve ser 1 mês após fatura 1
        vencimento_fatura_2 = contrato.calcular_vencimento_fatura_n(2)
        mes_diff = (vencimento_fatura_2.year - vencimento_fatura_1.year) * 12 + (vencimento_fatura_2.month - vencimento_fatura_1.month)
        dia_igual = vencimento_fatura_2.day == vencimento_fatura_1.day
        
        if mes_diff == 1 and dia_igual:
            print(f"   ✓ Fatura 2 está 1 mês após Fatura 1 no mesmo dia")
        else:
            print(f"   ✗ ERRO: Fatura 2 não está corretamente espaçada (diff: {mes_diff} meses, dia: {dia_igual})")
        
        # Validação 3: Data de disponibilidade é 3 dias após instalação para fatura 1
        dias_disponibilidade = (data_disponibilidade_1 - data_instalacao).days
        if dias_disponibilidade == 3:
            print(f"   ✓ Data de disponibilidade correta: 3 dias após instalação")
        else:
            print(f"   ✗ ERRO: Data de disponibilidade incorreta: {dias_disponibilidade} dias (esperado: 3)")
    
    print(f"\n{'=' * 80}")
    print("✅ TESTES CONCLUÍDOS")
    print(f"{'=' * 80}\n")


def testar_criacao_automatica():
    """Testa a criação automática de faturas ao salvar um contrato"""
    
    print("\n" + "=" * 80)
    print("TESTE DE CRIAÇÃO AUTOMÁTICA DE FATURAS")
    print("=" * 80)
    
    # Criar ou buscar safra de teste
    safra, _ = SafraM10.objects.get_or_create(
        mes_referencia=date(2025, 12, 1),
        defaults={'total_instalados': 0, 'total_ativos': 0}
    )
    
    # Criar contrato real no BD
    contrato = ContratoM10.objects.create(
        safra=safra,
        numero_contrato='TESTE-AUTO-001',
        cliente_nome='Cliente Teste Auto',
        cpf_cliente='98765432100',
        data_instalacao=date(2025, 12, 15),
        plano_original='Plano 100MB',
        plano_atual='Plano 100MB',
        valor_plano=100.00,
        status_contrato='ATIVO'
    )
    
    print(f"\n✅ Contrato criado: {contrato.numero_contrato}")
    print(f"📅 Data de instalação: {contrato.data_instalacao.strftime('%d/%m/%Y')}")
    print(f"📦 Safra calculada: {contrato.safra}")
    
    # Verificar faturas criadas
    faturas = FaturaM10.objects.filter(contrato=contrato).order_by('numero_fatura')
    
    print(f"\n📋 Faturas criadas automaticamente: {faturas.count()}")
    
    if faturas.count() == 10:
        print("✅ Quantidade correta de faturas (10)")
        
        print("\n📊 Resumo das faturas:")
        for fatura in faturas:
            print(f"   Fatura {fatura.numero_fatura}: "
                  f"Venc: {fatura.data_vencimento.strftime('%d/%m/%Y')} | "
                  f"Disp: {fatura.data_disponibilidade.strftime('%d/%m/%Y') if fatura.data_disponibilidade else 'N/A'} | "
                  f"Valor: R$ {fatura.valor:.2f}")
    else:
        print(f"❌ ERRO: Quantidade incorreta de faturas ({faturas.count()}, esperado: 10)")
    
    # Limpar teste
    print(f"\n🗑️  Removendo contrato de teste...")
    contrato.delete()
    print("✅ Contrato removido")
    
    print(f"\n{'=' * 80}")
    print("✅ TESTE CONCLUÍDO")
    print(f"{'=' * 80}\n")


if __name__ == '__main__':
    print("\n🧪 INICIANDO TESTES DE CÁLCULO DE VENCIMENTOS\n")
    
    # Teste 1: Cálculo manual
    testar_calculo_vencimentos()
    
    # Teste 2: Criação automática
    testar_criacao_automatica()
    
    print("\n✅ TODOS OS TESTES CONCLUÍDOS!\n")
