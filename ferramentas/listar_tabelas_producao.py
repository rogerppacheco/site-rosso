#!/usr/bin/env python
"""
Listar tabelas do banco em producao
"""
import sys
from urllib.parse import urlparse

DB_URL = "mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45"

try:
    import mysql.connector
    
    parsed = urlparse(DB_URL)
    
    connection = mysql.connector.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/')
    )
    
    cursor = connection.cursor()
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    
    print("Tabelas no banco de producao:")
    print("-" * 60)
    
    # Filtrar tabelas relacionadas a vendas
    venda_tables = []
    for table in tables:
        table_name = table[0]
        print(f"  {table_name}")
        if 'venda' in table_name.lower():
            venda_tables.append(table_name)
    
    if venda_tables:
        print(f"\nTabelas com 'venda' no nome:")
        for t in venda_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {t}")
            count = cursor.fetchone()[0]
            print(f"  - {t}: {count} registros")
    
    cursor.close()
    connection.close()
    
except Exception as e:
    print(f"Erro: {e}")
    sys.exit(1)
