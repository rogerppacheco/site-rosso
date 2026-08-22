#!/usr/bin/env python
"""
Script para sincronizar TODAS as tabelas principais do banco em producao.
Ordem: Usuarios, Grupos, Perfis, Clientes, Planos, StatusCRM, Vendas, etc.
"""
import os
import sys
from urllib.parse import urlparse

DB_URL = "mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45"

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

print("=" * 80)
print("SINCRONIZACAO COMPLETA - PRODUCAO -> LOCAL")
print("=" * 80)

try:
    import mysql.connector
    from mysql.connector import Error
    from django.db import transaction, connection as db_connection
    from django.contrib.auth.models import Group
    from usuarios.models import Usuario, Perfil
    from crm_app.models import (Cliente, Plano, FormaPagamento, StatusCRM, 
                                MotivoPendencia, Venda, Operadora)
    
    # Parse URL
    parsed = urlparse(DB_URL)
    
    # Conectar
    connection = mysql.connector.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/')
    )
    
    print(f"\nOK Conectado ao banco em producao!")
    cursor = connection.cursor(dictionary=True)
    
    # PASSO 1: GRUPOS (ja feito anteriormente, pular)
    print("\n[1/9] Grupos: OK (ja sincronizados)")
    
    # PASSO 2: USUARIOS (ja feito anteriormente, pular)
    print("[2/9] Usuarios: OK (ja sincronizados)")
    
    # PASSO 3: PERFIS
    print("\n[3/9] Sincronizando Perfis...")
    cursor.execute("SELECT * FROM usuarios_perfil")
    perfis_data = cursor.fetchall()
    print(f"  Encontrados {len(perfis_data)} perfis")
    
    Perfil.objects.all().delete()
    for p in perfis_data:
        Perfil.objects.create(
            id=p['id'],
            nome=p['nome'],
            descricao=p.get('descricao', '')
        )
    print(f"  OK {Perfil.objects.count()} perfis criados")
    
    # PASSO 4: OPERADORAS
    print("\n[4/9] Sincronizando Operadoras...")
    cursor.execute("SELECT * FROM crm_operadora")
    operadoras = cursor.fetchall()
    print(f"  Encontrados {len(operadoras)} operadoras")
    
    Operadora.objects.all().delete()
    for op in operadoras:
        Operadora.objects.create(
            id=op['id'],
            nome=op.get('nome', ''),
            cnpj=op.get('cnpj'),
            ativo=op.get('ativo', True)
        )
    print(f"  OK {Operadora.objects.count()} operadoras criadas")
    
    # PASSO 5: CLIENTES
    print("\n[5/9] Sincronizando Clientes...")
    cursor.execute("SELECT COUNT(*) as total FROM crm_cliente")
    total = cursor.fetchone()['total']
    print(f"  Encontrados {total} clientes")
    
    resposta = input(f"  Continuar? (s/n): ")
    if resposta.lower() != 's':
        print("Cancelado")
        sys.exit(0)
    
    cursor.execute("SELECT * FROM crm_cliente ORDER BY id")
    clientes = cursor.fetchall()
    
    Cliente.objects.all().delete()
    criados = 0
    for i, c in enumerate(clientes):
        try:
            Cliente.objects.create(
                id=c['id'],
                nome_razao_social=c.get('nome_razao_social', ''),
                cpf_cnpj=c.get('cpf_cnpj', ''),
                email=c.get('email')
            )
            criados += 1
            if (i + 1) % 500 == 0:
                print(f"  Progresso: {i + 1}/{len(clientes)}...")
        except Exception as e:
            if criados < 5:
                print(f"  Erro cliente ID {c['id']}: {str(e)[:60]}")
    print(f"  OK {Cliente.objects.count()} clientes criados")
    
    # PASSO 6: PLANOS
    print("\n[6/9] Sincronizando Planos...")
    cursor.execute("SELECT * FROM crm_plano")
    planos = cursor.fetchall()
    print(f"  Encontrados {len(planos)} planos")
    
    Plano.objects.all().delete()
    for p in planos:
        Plano.objects.create(
            id=p['id'],
            nome=p.get('nome', ''),
            valor=p.get('valor', 0),
            operadora_id=p.get('operadora_id'),
            beneficios=p.get('beneficios'),
            ativo=p.get('ativo', True),
            comissao_base=p.get('comissao_base', 0)
        )
    print(f"  OK {Plano.objects.count()} planos criados")
    
    # PASSO 7: FORMA PAGAMENTO
    print("\n[7/9] Sincronizando Formas de Pagamento...")
    cursor.execute("SELECT * FROM crm_forma_pagamento")
    formas = cursor.fetchall()
    print(f"  Encontrados {len(formas)} formas de pagamento")
    
    FormaPagamento.objects.all().delete()
    for f in formas:
        FormaPagamento.objects.create(
            id=f['id'],
            nome=f.get('nome', ''),
            ativo=f.get('ativo', True),
            aplica_desconto=f.get('aplica_desconto', False)
        )
    print(f"  OK {FormaPagamento.objects.count()} formas criadas")
    
    # PASSO 8: STATUS CRM
    print("\n[8/9] Sincronizando Status CRM...")
    cursor.execute("SELECT * FROM crm_status")
    status = cursor.fetchall()
    print(f"  Encontrados {len(status)} status")
    
    StatusCRM.objects.all().delete()
    for s in status:
        StatusCRM.objects.create(
            id=s['id'],
            nome=s.get('nome', ''),
            tipo=s.get('tipo', 'Tratamento'),
            estado=s.get('estado'),
            cor=s.get('cor', '#FFFFFF')
        )
    print(f"  OK {StatusCRM.objects.count()} status criados")
    
    # PASSO 9: VENDAS
    print("\n[9/9] Sincronizando Vendas...")
    cursor.execute("SELECT COUNT(*) as total FROM crm_venda")
    total = cursor.fetchone()['total']
    print(f"  Encontrados {total} vendas")
    
    cursor.execute("SELECT * FROM crm_venda ORDER BY id")
    vendas = cursor.fetchall()
    
    Venda.objects.all().delete()
    criados = 0
    erros = 0
    
    # Desabilitar checks de FK temporariamente
    with db_connection.cursor() as db_cursor:
        db_cursor.execute('PRAGMA foreign_keys = OFF')
    
    for i, v in enumerate(vendas):
        try:
            # Criar dicionário com apenas campos válidos
            campos = {}
            for campo, valor in v.items():
                if campo != 'id' and hasattr(Venda, campo):
                    # Campos _id passam direto
                    campos[campo] = valor
            
            venda = Venda(id=v['id'], **campos)
            venda.save()
            criados += 1
            
            if (i + 1) % 100 == 0:
                print(f"  Progresso: {i + 1}/{len(vendas)}...")
                
        except Exception as e:
            erros += 1
            if erros <= 3:
                print(f"  Erro venda ID {v.get('id', '?')}: {str(e)[:70]}")
    
    # Reabilitar checks
    with db_connection.cursor() as db_cursor:
        db_cursor.execute('PRAGMA foreign_keys = ON')
    
    print(f"  OK {criados} vendas criadas ({erros} erros)")
    
    cursor.close()
    connection.close()
    
    print("\n" + "=" * 80)
    print("SINCRONIZACAO COMPLETA!")
    print(f"  Perfis: {Perfil.objects.count()}")
    print(f"  Operadoras: {Operadora.objects.count()}")
    print(f"  Clientes: {Cliente.objects.count()}")
    print(f"  Planos: {Plano.objects.count()}")
    print(f"  Formas Pgto: {FormaPagamento.objects.count()}")
    print(f"  Status CRM: {StatusCRM.objects.count()}")
    print(f"  Vendas: {Venda.objects.count()}")
    print("=" * 80)
    
except ImportError:
    print("ERRO mysql-connector-python nao esta instalado")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mysql-connector-python", "-q"])
    print("OK Instalado. Execute novamente!")
    sys.exit(0)
except KeyboardInterrupt:
    print("\n\nCancelado pelo usuario")
    sys.exit(1)
except Exception as e:
    print(f"ERRO: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
