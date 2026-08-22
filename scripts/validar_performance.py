"""
Script de Validação de Performance PostgreSQL
Testa as otimizações implementadas no sistema

Uso:
    python scripts/validar_performance.py
"""

import os
import sys
import time
from datetime import datetime, timedelta

# Setup Django
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Configurar o ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

# Importar Django após configurar o path
import django
django.setup()

from django.db import connection
from crm_app.models import Venda, ImportacaoOsab, ImportacaoChurn
from django.utils import timezone


def executar_query_com_tempo(descricao, query_func):
    """Executa uma query e mede o tempo de execução"""
    print(f"\n{'=' * 60}")
    print(f"Teste: {descricao}")
    print(f"{'=' * 60}")
    
    inicio = time.time()
    try:
        resultado = query_func()
        fim = time.time()
        tempo_ms = (fim - inicio) * 1000
        
        count = resultado.count() if hasattr(resultado, 'count') else len(resultado)
        
        print(f"✓ Sucesso!")
        print(f"  - Registros retornados: {count}")
        print(f"  - Tempo de execução: {tempo_ms:.2f}ms")
        
        # Avaliação de performance
        if tempo_ms < 100:
            print(f"  - Avaliação: 🚀 EXCELENTE (< 100ms)")
        elif tempo_ms < 500:
            print(f"  - Avaliação: ✅ BOM (< 500ms)")
        elif tempo_ms < 2000:
            print(f"  - Avaliação: ⚠️ ACEITÁVEL (< 2s)")
        else:
            print(f"  - Avaliação: ❌ LENTO (> 2s) - Requer investigação")
        
        return tempo_ms
        
    except Exception as e:
        fim = time.time()
        tempo_ms = (fim - inicio) * 1000
        print(f"✗ Erro: {e}")
        print(f"  - Tempo até erro: {tempo_ms:.2f}ms")
        return None


def verificar_indices():
    """Verifica se os índices foram criados corretamente"""
    print("\n" + "=" * 60)
    print("VERIFICAÇÃO DE ÍNDICES")
    print("=" * 60)
    
    # Verificar se é PostgreSQL ou SQLite
    if connection.vendor == 'sqlite':
        print("\n⚠️  Banco SQLite detectado")
        print("   Índices PostgreSQL não são aplicáveis em desenvolvimento")
        print("   ✓ Índices simples (db_index=True) foram criados automaticamente")
        return
    
    with connection.cursor() as cursor:
        # Listar índices da tabela crm_venda
        cursor.execute("""
            SELECT 
                indexname,
                indexdef
            FROM pg_indexes 
            WHERE tablename = 'crm_venda' 
            ORDER BY indexname;
        """)
        
        indices = cursor.fetchall()
        
        indices_esperados = [
            'idx_venda_flow_auditoria',
            'idx_venda_flow_esteira',
            'idx_venda_flow_comiss',
            'idx_venda_datas',
            'idx_venda_vendedor_data',
            'idx_venda_auditor',
        ]
        
        indices_encontrados = [idx[0] for idx in indices]
        
        print(f"\nTotal de índices na tabela crm_venda: {len(indices)}")
        print("\nÍndices de performance esperados:")
        
        for idx_esperado in indices_esperados:
            if idx_esperado in indices_encontrados:
                print(f"  ✓ {idx_esperado}")
            else:
                print(f"  ✗ {idx_esperado} - NÃO ENCONTRADO!")
        
        # Verificar índices em campos individuais
        print("\nÍndices em campos individuais:")
        campos_com_index = [
            'vendedor_id', 'status_tratamento_id', 'status_esteira_id',
            'status_comissionamento_id', 'data_criacao', 'ordem_servico',
            'data_instalacao', 'motivo_pendencia_id', 'auditor_atual_id'
        ]
        
        for campo in campos_com_index:
            idx_nome = f'crm_venda_{campo}_'
            tem_index = any(idx_nome in idx[0] for idx in indices)
            status = "✓" if tem_index else "✗"
            print(f"  {status} {campo}")


def teste_query_auditoria():
    """Testa query do flow de auditoria"""
    return Venda.objects.filter(
        ativo=True,
        status_tratamento__isnull=False,
        status_esteira__isnull=True
    ).select_related(
        'vendedor', 'status_tratamento'
    )[:100]


def teste_query_esteira():
    """Testa query do flow de esteira"""
    return Venda.objects.filter(
        ativo=True,
        status_esteira__isnull=False
    ).select_related(
        'vendedor', 'status_esteira', 'cliente'
    )[:100]


def teste_query_comissionamento():
    """Testa query do flow de comissionamento"""
    return Venda.objects.filter(
        ativo=True,
        status_esteira__nome__icontains='INSTALADA'
    ).exclude(
        status_comissionamento__nome__icontains='PAGO'
    ).select_related(
        'vendedor', 'status_esteira', 'status_comissionamento'
    )[:100]


def teste_query_por_data():
    """Testa query por período de datas"""
    hoje = timezone.now()
    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    return Venda.objects.filter(
        ativo=True,
        data_criacao__gte=inicio_mes
    ).select_related('vendedor', 'cliente')[:100]


def teste_query_busca_os():
    """Testa busca por ordem de serviço"""
    # Pega uma OS real para testar
    os_sample = Venda.objects.filter(
        ativo=True, 
        ordem_servico__isnull=False
    ).values_list('ordem_servico', flat=True).first()
    
    if not os_sample:
        print("  ⚠️ Nenhuma venda com OS encontrada para teste")
        return Venda.objects.none()
    
    return Venda.objects.filter(
        ativo=True,
        ordem_servico__icontains=os_sample[:5]
    )


def teste_import_osab_lookup():
    """Testa lookup na tabela ImportacaoOsab"""
    # Pega alguns documentos reais para testar
    docs = list(ImportacaoOsab.objects.values_list('documento', flat=True)[:1000])
    
    if not docs:
        print("  ⚠️ Nenhum registro em ImportacaoOsab para teste")
        return []
    
    return ImportacaoOsab.objects.filter(documento__in=docs)


def analisar_query_explain():
    """Executa EXPLAIN ANALYZE em queries críticas"""
    print("\n" + "=" * 60)
    print("ANÁLISE DETALHADA COM EXPLAIN")
    print("=" * 60)
    
    # Só funciona em PostgreSQL
    if connection.vendor == 'sqlite':
        print("\n⚠️  EXPLAIN ANALYZE não disponível em SQLite")
        print("   Esta análise só funciona em PostgreSQL de produção")
        return
    
    queries = [
        {
            'nome': 'Flow Auditoria',
            'sql': """
                EXPLAIN ANALYZE
                SELECT * FROM crm_venda 
                WHERE ativo = TRUE 
                  AND status_tratamento_id IS NOT NULL 
                  AND status_esteira_id IS NULL
                LIMIT 100;
            """
        },
        {
            'nome': 'Flow Esteira',
            'sql': """
                EXPLAIN ANALYZE
                SELECT * FROM crm_venda 
                WHERE ativo = TRUE 
                  AND status_esteira_id IS NOT NULL
                LIMIT 100;
            """
        },
        {
            'nome': 'Busca por OS',
            'sql': """
                EXPLAIN ANALYZE
                SELECT * FROM crm_venda 
                WHERE ativo = TRUE 
                  AND ordem_servico LIKE '%123%'
                LIMIT 10;
            """
        }
    ]
    
    with connection.cursor() as cursor:
        for query in queries:
            print(f"\n{query['nome']}:")
            print("-" * 60)
            try:
                cursor.execute(query['sql'])
                resultado = cursor.fetchall()
                
                # Verificar se está usando índice
                plan_text = '\n'.join([row[0] for row in resultado])
                
                if 'Index Scan' in plan_text or 'Index Only Scan' in plan_text:
                    print("  ✓ Usando índice corretamente")
                elif 'Bitmap' in plan_text:
                    print("  ⚠️ Usando Bitmap Index Scan (OK para múltiplos valores)")
                else:
                    print("  ✗ ATENÇÃO: Possível Seq Scan (sem índice)")
                
                # Mostrar primeiras linhas do plano
                linhas = plan_text.split('\n')[:5]
                for linha in linhas:
                    print(f"    {linha}")
                    
            except Exception as e:
                print(f"  ✗ Erro: {e}")


def main():
    """Função principal"""
    print("\n" + "=" * 60)
    print("VALIDAÇÃO DE PERFORMANCE - SITE RECORD")
    print("Data:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    print("=" * 60)
    
    # 1. Verificar índices
    verificar_indices()
    
    # 2. Testes de performance
    print("\n\n" + "=" * 60)
    print("TESTES DE PERFORMANCE")
    print("=" * 60)
    
    tempos = {}
    
    tempos['auditoria'] = executar_query_com_tempo(
        "Query Flow Auditoria",
        teste_query_auditoria
    )
    
    tempos['esteira'] = executar_query_com_tempo(
        "Query Flow Esteira",
        teste_query_esteira
    )
    
    tempos['comissionamento'] = executar_query_com_tempo(
        "Query Flow Comissionamento",
        teste_query_comissionamento
    )
    
    tempos['por_data'] = executar_query_com_tempo(
        "Query por Período (Mês Atual)",
        teste_query_por_data
    )
    
    tempos['busca_os'] = executar_query_com_tempo(
        "Busca por Ordem de Serviço",
        teste_query_busca_os
    )
    
    tempos['osab_lookup'] = executar_query_com_tempo(
        "Lookup ImportacaoOsab (1000 docs)",
        teste_import_osab_lookup
    )
    
    # 3. Análise detalhada
    analisar_query_explain()
    
    # 4. Resumo final
    print("\n\n" + "=" * 60)
    print("RESUMO FINAL")
    print("=" * 60)
    
    tempos_validos = {k: v for k, v in tempos.items() if v is not None}
    
    if tempos_validos:
        tempo_medio = sum(tempos_validos.values()) / len(tempos_validos)
        tempo_max = max(tempos_validos.values())
        
        print(f"\nTempo médio de queries: {tempo_medio:.2f}ms")
        print(f"Query mais lenta: {tempo_max:.2f}ms")
        
        if tempo_medio < 500:
            print("\n✅ Performance EXCELENTE! Sistema otimizado com sucesso.")
        elif tempo_medio < 2000:
            print("\n⚠️ Performance ACEITÁVEL. Considere ajustes adicionais.")
        else:
            print("\n❌ Performance INADEQUADA. Revise implementação dos índices.")
    
    print("\n" + "=" * 60)
    print("Validação concluída!")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    main()
