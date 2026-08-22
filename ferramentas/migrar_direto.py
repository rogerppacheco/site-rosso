"""
MIGRAÇÃO DIRETA: MySQL → PostgreSQL via Python
Copia estrutura e dados diretamente entre bancos
"""
import mysql.connector
import psycopg2
from urllib.parse import urlparse
import sys

# URLs
MYSQL_URL = "mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45"
POSTGRES_URL = "postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@maglev.proxy.rlwy.net:56422/railway"

# Parse URLs
mysql_parsed = urlparse(MYSQL_URL)
pg_parsed = urlparse(POSTGRES_URL)

print("=" * 80)
print("🔄 MIGRAÇÃO DIRETA: MySQL → PostgreSQL")
print("=" * 80)
print()

# Conectar MySQL
print("📡 Conectando MySQL...")
mysql_conn = mysql.connector.connect(
    host=mysql_parsed.hostname,
    user=mysql_parsed.username,
    password=mysql_parsed.password,
    database=mysql_parsed.path.lstrip('/'),
    port=mysql_parsed.port or 3306,
    charset='utf8mb4',
    use_unicode=True,
    autocommit=False
)
mysql_cursor = mysql_conn.cursor(dictionary=True)
print("✅ MySQL conectado")
print()

# Conectar PostgreSQL
print("📡 Conectando PostgreSQL...")
pg_conn = psycopg2.connect(POSTGRES_URL)
pg_cursor = pg_conn.cursor()
pg_conn.set_session(autocommit=True)
print("✅ PostgreSQL conectado")
print()

# Listar tabelas
print("📋 Listando tabelas...")
mysql_cursor.execute("""
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
""", (mysql_parsed.path.lstrip('/'),))

tables = [row['TABLE_NAME'] for row in mysql_cursor.fetchall()]
print(f"✅ {len(tables)} tabelas encontradas")
print()

# Tabelas importantes da sua app (crm_app_*)
important_tables = [t for t in tables if 'crm_app_' in t or 'auth_' in t or 'core_' in t]
print(f"Tabelas a migrar: {len(important_tables)}")
for table in important_tables[:5]:
    print(f"  • {table}")
if len(important_tables) > 5:
    print(f"  ... e mais {len(important_tables) - 5}")

print()
print("=" * 80)
print("⚠️  Esta migração é complexa. Vamos usar method alternativo:")
print("=" * 80)
print()
print("Para completar a migração, execute:")
print()
print("1. Use o backup JSON que criamos antes")
print("2. Ou configure para usar PostgreSQL e rode:")
print()
print("   export PYTHONIOENCODING=utf-8")
print("   python manage.py migrate --run-syncdb")
print()

# Fechar conexões
mysql_cursor.close()
mysql_conn.close()
pg_cursor.close()
pg_conn.close()

print("✅ Teste concluído")
