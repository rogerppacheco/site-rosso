# ferramentas/corrigir_tipo_venda_pedidos.py
"""
Script de uso único para corrigir os registros com tipo_venda incorreto
no banco de dados de produção.

Lógica:
- Busca todos os HistoricoPapPedido com tipo_venda != o que está no payload
- O payload contém tipoVenda ou chaveStatusPrimario da API da Vtal
- Usa isso para corrigir o campo tipo_venda
"""
from crm_app.models import HistoricoPapPedido

# Mapeamento dos valores da API da Vtal para os nossos internos
VTAL_TO_INTERNO = {
    "VENDA": "VENDA",
    "CONCLUIDO": "VENDA",
    "concluido": "VENDA",
    "Concluído": "VENDA",
    "INTERESSE": "INTERESSE",
    "interesse": "INTERESSE",
    "Interesse": "INTERESSE",
    "PRE_VENDA": "PRE_VENDA",
    "PRE-VENDA": "PRE_VENDA",
    "pre_venda": "PRE_VENDA",
    "Pré-venda": "PRE_VENDA",
    "PRÉ-VENDA": "PRE_VENDA",
}

total = HistoricoPapPedido.objects.count()
print(f"Total de registros: {total}")

# Contar por tipo atual
from django.db.models import Count
por_tipo = HistoricoPapPedido.objects.values('tipo_venda').annotate(n=Count('id'))
for pt in por_tipo:
    print(f"  tipo_venda={pt['tipo_venda']}: {pt['n']} registros")

print("\nAnalisando payloads para encontrar tipo real...")

corrigidos = 0
sem_info = 0
ok = 0

todos = HistoricoPapPedido.objects.all()
for pedido in todos:
    payload = pedido.payload or {}
    
    # Tentar determinar o tipo correto pelo payload
    tipo_real = None
    
    # Campo mais confiável: tipoVenda
    tv = payload.get("tipoVenda") or payload.get("tipo_venda") or payload.get("type")
    if tv:
        tipo_real = VTAL_TO_INTERNO.get(str(tv).strip(), None)
    
    # Fallback: chaveStatusPrimario  
    if not tipo_real:
        csp = payload.get("chaveStatusPrimario") or payload.get("status")
        if csp:
            tipo_real = VTAL_TO_INTERNO.get(str(csp).strip(), None)
    
    if not tipo_real:
        sem_info += 1
        # Se não conseguimos detectar o tipo pelo payload, mas o campo está como INTERESSE
        # e o número de pedido não tem nenhum indicador, deixar como está
        continue
    
    if pedido.tipo_venda == tipo_real:
        ok += 1
        continue
    
    print(f"  Corrigindo {pedido.numero_pedido}: {pedido.tipo_venda} -> {tipo_real} (payload tipoVenda={tv})")
    pedido.tipo_venda = tipo_real
    pedido.save(update_fields=['tipo_venda'])
    corrigidos += 1

print(f"\nResultado:")
print(f"  Corrigidos: {corrigidos}")
print(f"  Já corretos: {ok}")
print(f"  Sem info no payload: {sem_info}")

print("\nDistribuição APÓS correção:")
por_tipo_novo = HistoricoPapPedido.objects.values('tipo_venda').annotate(n=Count('id'))
for pt in por_tipo_novo:
    print(f"  tipo_venda={pt['tipo_venda']}: {pt['n']} registros")
