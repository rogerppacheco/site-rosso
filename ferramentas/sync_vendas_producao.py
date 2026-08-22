#!/usr/bin/env python
"""
Script para sincronizar APENAS VENDAS do banco em producao para o local.
"""
import os
import sys
from urllib.parse import urlparse

# URL do banco em producao
DB_URL = "mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45"

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

print("=" * 80)
print("SINCRONIZACAO DE VENDAS - PRODUCAO -> LOCAL")
print("=" * 80)

try:
    import mysql.connector
    from mysql.connector import Error
    
    # Parse da URL
    parsed = urlparse(DB_URL)
    
    connection = mysql.connector.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/')
    )
    
    print(f"\nOK Conectado ao banco em producao!")
    
    # Buscar vendas
    print("\n[1/2] Buscando vendas em producao...")
    
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM crm_venda")
    result = cursor.fetchone()
    total_vendas = result['total']
    
    print(f"Total de vendas na producao: {total_vendas}")
    
    if total_vendas == 0:
        print("Nenhuma venda encontrada em producao!")
        sys.exit(0)
    
    # Confirmar
    resposta = input(f"\nDeseja baixar {total_vendas} vendas? (s/n): ")
    if resposta.lower() != 's':
        print("Cancelado pelo usuario")
        sys.exit(0)
    
    print("\nBuscando dados das vendas...")
    cursor.execute("SELECT * FROM crm_venda ORDER BY id")
    vendas = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    print(f"OK {len(vendas)} vendas carregadas da producao")
    
    # Inserir no banco local
    print("\n[2/2] Inserindo vendas no banco local...")
    
    from crm_app.models import Venda
    from usuarios.models import Usuario
    from django.db import transaction
    
    # Limpar vendas antigas
    total_antigas = Venda.objects.count()
    print(f"Removendo {total_antigas} vendas antigas do banco local...")
    Venda.objects.all().delete()
    
    # Inserir em lote
    print("Inserindo novas vendas...")
    vendas_criadas = 0
    vendas_erro = 0
    
    with transaction.atomic():
        for i, venda_data in enumerate(vendas):
            try:
                # Criar dicionário apenas com campos que existem no modelo
                campos_venda = {}
                for campo, valor in venda_data.items():
                    if campo == 'id':
                        campos_venda['id'] = valor
                    elif hasattr(Venda, campo):
                        # Converter campos _id para o ID direto
                        if campo.endswith('_id'):
                            campos_venda[campo] = valor
                        else:
                            campos_venda[campo] = valor
                
                venda = Venda(**campos_venda)
                venda.save()
                vendas_criadas += 1
                
                # Mostrar progresso a cada 100
                if (i + 1) % 100 == 0:
                    print(f"  Progresso: {i + 1}/{len(vendas)} vendas...")
                    
            except Exception as e:
                vendas_erro += 1
                if vendas_erro <= 5:  # Mostrar apenas os primeiros 5 erros
                    print(f"  Erro ao inserir venda ID {venda_data.get('id', '?')}: {str(e)[:100]}")
                continue
    
    # Verificar resultado
    total_final = Venda.objects.count()
    
    print("\n" + "=" * 80)
    print("OK SINCRONIZACAO CONCLUIDA!")
    print(f"  Vendas inseridas com sucesso: {vendas_criadas}")
    print(f"  Erros: {vendas_erro}")
    print(f"  Total no banco local: {total_final}")
    print("=" * 80)
    
except ImportError:
    print("ERRO mysql-connector-python nao esta instalado")
    print("   Instalando...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mysql-connector-python", "-q"])
    print("   OK Instalado. Execute novamente!")
    sys.exit(0)
except Error as e:
    print(f"ERRO de conexao: {e}")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n\nCancelado pelo usuario")
    sys.exit(1)
except Exception as e:
    print(f"ERRO: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
