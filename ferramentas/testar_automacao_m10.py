"""
TESTE DO SISTEMA DE AUTOMAÇÃO M-10

Este script testa se os signals estão funcionando corretamente
"""

import os
import django
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import Venda, Cliente, ContratoM10, SafraM10, Plano
from usuarios.models import Usuario

print("=" * 70)
print("TESTE DE AUTOMAÇÃO M-10")
print("=" * 70)

# Pegar um cliente e vendedor existentes
cliente = Cliente.objects.first()
vendedor = Usuario.objects.first()
plano = Plano.objects.first()

if not cliente or not vendedor or not plano:
    print("\n❌ ERRO: Faltam dados para o teste (cliente, vendedor ou plano)")
    print(f"   - Clientes: {Cliente.objects.count()}")
    print(f"   - Usuários: {Usuario.objects.count()}")
    print(f"   - Planos: {Plano.objects.count()}")
    exit()

print(f"\n✅ Cliente: {cliente.nome_razao_social}")
print(f"✅ Vendedor: {vendedor.username}")
print(f"✅ Plano: {plano.nome}")

# Criar uma venda de teste
print("\n" + "-" * 70)
print("CRIANDO VENDA DE TESTE...")
print("-" * 70)

venda_teste = Venda.objects.create(
    ativo=True,
    cliente=cliente,
    vendedor=vendedor,
    plano=plano,
    data_instalacao=date(2026, 1, 15),
    ordem_servico="TEST-OS-12345",
    forma_entrada='APP',
    telefone1='11999999999',
    cep='01310-100',
    logradouro='Av Paulista',
    numero_residencia='1000',
    bairro='Bela Vista',
    cidade='São Paulo',
    estado='SP'
)

print(f"\n✅ Venda {venda_teste.id} criada com sucesso!")
print(f"   - O.S: {venda_teste.ordem_servico}")
print(f"   - Data instalação: {venda_teste.data_instalacao}")

# Verificar se o ContratoM10 foi criado automaticamente
print("\n" + "-" * 70)
print("VERIFICANDO AUTOMAÇÃO...")
print("-" * 70)

try:
    contrato = ContratoM10.objects.get(venda=venda_teste)
    print(f"\n🎉 SUCESSO! ContratoM10 {contrato.id} criado AUTOMATICAMENTE!")
    print(f"   - Número contrato: {contrato.numero_contrato}")
    print(f"   - O.S: {contrato.ordem_servico}")
    print(f"   - Cliente: {contrato.cliente_nome}")
    print(f"   - Vendedor: {contrato.vendedor.username if contrato.vendedor else 'N/A'}")
    print(f"   - Data instalação: {contrato.data_instalacao}")
    print(f"   - Status: {contrato.status_contrato}")
    print(f"   - Número contrato definitivo: {contrato.numero_contrato_definitivo or '(ainda não preenchido)'}")
    print(f"   - Última sinc. FPD: {contrato.data_ultima_sincronizacao_fpd or '(ainda não sincronizado)'}")
    
    # Verificar SafraM10
    safra = SafraM10.objects.filter(mes_referencia=date(2026, 1, 1)).first()
    if safra:
        print(f"\n✅ SafraM10 também criada/atualizada automaticamente!")
        print(f"   - Mês: {safra.mes_referencia.strftime('%m/%Y')}")
        print(f"   - Total instalados: {safra.total_instalados}")
    
    print("\n" + "=" * 70)
    print("✅ AUTOMAÇÃO FUNCIONANDO PERFEITAMENTE!")
    print("=" * 70)
    
except ContratoM10.DoesNotExist:
    print(f"\n❌ ERRO: ContratoM10 NÃO foi criado automaticamente!")
    print("   Verifique se os signals estão registrados corretamente.")
    
except Exception as e:
    print(f"\n❌ ERRO: {e}")

# Limpar venda de teste
print("\n🗑️  Limpando venda de teste...")
venda_teste.delete()
print("✅ Venda de teste removida.")

print("\n" + "=" * 70)
print("TESTE FINALIZADO")
print("=" * 70)
