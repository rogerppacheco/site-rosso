# Generated manually for PostgreSQL performance optimization

from django.db import migrations, connection


def create_indexes_postgresql(apps, schema_editor):
    """Cria índices otimizados apenas para PostgreSQL"""
    if connection.vendor != 'postgresql':
        print("⚠️  Pulando criação de índices PostgreSQL - banco atual é", connection.vendor)
        return
    
    with connection.cursor() as cursor:
        # Índice parcial para flow de auditoria
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_venda_flow_auditoria 
            ON crm_venda(status_tratamento_id, ativo) 
            WHERE status_tratamento_id IS NOT NULL AND status_esteira_id IS NULL AND ativo IS TRUE;
        """)
        
        # Índice parcial para flow de esteira
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_venda_flow_esteira 
            ON crm_venda(status_esteira_id, ativo) 
            WHERE status_esteira_id IS NOT NULL AND ativo IS TRUE;
        """)
        
        # Índice parcial para flow de comissionamento
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_venda_flow_comiss 
            ON crm_venda(status_esteira_id, status_comissionamento_id) 
            WHERE status_esteira_id IS NOT NULL;
        """)
        
        # Índice composto para filtros de data
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_venda_datas 
            ON crm_venda(data_criacao, data_instalacao) 
            WHERE ativo IS TRUE;
        """)
        
        # Índice composto para vendedor + data
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_venda_vendedor_data 
            ON crm_venda(vendedor_id, data_criacao DESC) 
            WHERE ativo IS TRUE;
        """)
        
        # Índice para buscas por auditoria alocada
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_venda_auditor 
            ON crm_venda(auditor_atual_id) 
            WHERE auditor_atual_id IS NOT NULL AND ativo IS TRUE;
        """)
        
        print("✓ Índices de performance PostgreSQL criados com sucesso!")


def drop_indexes_postgresql(apps, schema_editor):
    """Remove índices ao reverter migration"""
    if connection.vendor != 'postgresql':
        return
    
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS idx_venda_flow_auditoria;")
        cursor.execute("DROP INDEX IF EXISTS idx_venda_flow_esteira;")
        cursor.execute("DROP INDEX IF EXISTS idx_venda_flow_comiss;")
        cursor.execute("DROP INDEX IF EXISTS idx_venda_datas;")
        cursor.execute("DROP INDEX IF EXISTS idx_venda_vendedor_data;")
        cursor.execute("DROP INDEX IF EXISTS idx_venda_auditor;")


class Migration(migrations.Migration):
    # CRÍTICO: Desabilitar transação atômica para CREATE INDEX CONCURRENTLY
    atomic = False

    dependencies = [
        ('crm_app', '0065_alter_importacaoosab_documento_and_more'),
    ]

    operations = [
        migrations.RunPython(create_indexes_postgresql, drop_indexes_postgresql),
    ]
