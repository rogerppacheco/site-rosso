"""
MIGRAÇÃO SEGURA: Exporta de MySQL e Importa em PostgreSQL
Versão simplificada - sem Django migrations
"""
import os
import sys
import json
from datetime import datetime
import psycopg2
import mysql.connector
from urllib.parse import urlparse

print("=" * 80)
print("🔄 MIGRAÇÃO MYSQL → POSTGRESQL")
print("=" * 80)
print()

# URLs
MYSQL_URL = "mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45"
POSTGRES_URL = "postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@maglev.proxy.rlwy.net:56422/railway"

# Parse URLs
mysql_parsed = urlparse(MYSQL_URL)
pg_parsed = urlparse(POSTGRES_URL)

print("📊 Conectando aos bancos...")
print()

# ============================================================================
# CONECTAR AO MYSQL
# ============================================================================
try:
    mysql_conn = mysql.connector.connect(
        host=mysql_parsed.hostname,
        user=mysql_parsed.username,
        password=mysql_parsed.password,
        database=mysql_parsed.path.lstrip('/'),
        port=mysql_parsed.port or 3306
    )
    mysql_cursor = mysql_conn.cursor()
    
    # Listar tabelas
    mysql_cursor.execute("SHOW TABLES")
    tables = [table[0] for table in mysql_cursor.fetchall()]
    print(f"✅ MySQL conectado: {len(tables)} tabelas encontradas")
    print()
    
    # Mostrar algumas tabelas
    print("   Tabelas encontradas:")
    for table in tables[:10]:
        mysql_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = mysql_cursor.fetchone()[0]
        print(f"   • {table}: {count} registros")
    
    if len(tables) > 10:
        print(f"   ... e mais {len(tables) - 10} tabelas")
    
    print()

except Exception as e:
    print(f"❌ Erro ao conectar MySQL: {e}")
    sys.exit(1)

# ============================================================================
# CONECTAR AO POSTGRESQL
# ============================================================================
print("Conectando ao PostgreSQL...")
print()

try:
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cursor = pg_conn.cursor()
    
    pg_cursor.execute("SELECT 1")
    print("✅ PostgreSQL conectado!")
    print()
    
except Exception as e:
    print(f"❌ Erro ao conectar PostgreSQL: {e}")
    sys.exit(1)

# ============================================================================
# PRÓXIMAS ETAPAS
# ============================================================================
print("=" * 80)
print("✅ Conexões validadas!")
print("=" * 80)
print()
print("Dados disponíveis para migração:")
print()

# Contar total de registros
mysql_cursor.execute("""
SELECT SUM(TABLE_ROWS) as total 
FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_SCHEMA = %s
""", (mysql_parsed.path.lstrip('/'),))

total_rows = mysql_cursor.fetchone()[0] or 0
print(f"   Total de registros no MySQL: {total_rows}")
print()

print("=" * 80)
print("⚠️  PRÓXIMO PASSO: Usar Django para migração (mais seguro)")
print("=" * 80)
print()
print("Execute:")
print("   python manage.py dumpdata --all > dump_mysql.json")
print()
print("Depois modifique settings.py para PostgreSQL e:")
print("   python manage.py loaddata dump_mysql.json")
print()

# Fechar conexões
mysql_cursor.close()
mysql_conn.close()
pg_cursor.close()
pg_conn.close()

print("✅ Teste de conexão concluído!")
print()
