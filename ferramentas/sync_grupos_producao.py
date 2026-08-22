#!/usr/bin/env python
"""
Script para sincronizar grupos e relacionamentos usuario-grupos do banco em producao.
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
print("SINCRONIZACAO DE GRUPOS E PERMISSOES - PRODUCAO -> LOCAL")
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
    print(f"   Host: {parsed.hostname}")
    print(f"   Database: {parsed.path.lstrip('/')}")
    
    # PASSO 1: Buscar grupos
    print("\n[1/3] Buscando grupos em producao...")
    
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM auth_group")
    grupos = cursor.fetchall()
    
    print(f"OK Encontrados {len(grupos)} grupo(s):")
    for grupo in grupos:
        print(f"   - ID: {grupo['id']}, Nome: {grupo['name']}")
    
    # PASSO 2: Buscar relacionamentos usuario-grupos
    print("\n[2/3] Buscando relacionamentos usuario-grupos...")
    
    cursor.execute("SELECT * FROM usuarios_usuario_groups")
    relacoes = cursor.fetchall()
    
    print(f"OK Encontrados {len(relacoes)} relacionamento(s)")
    
    cursor.close()
    connection.close()
    
    # PASSO 3: Restaurar no banco local
    print("\n[3/3] Restaurando no banco local...")
    
    from django.contrib.auth.models import Group
    from usuarios.models import Usuario
    
    # Limpar grupos antigos
    Group.objects.all().delete()
    print("   - Grupos antigos removidos")
    
    # Inserir novos grupos
    grupos_criados = {}
    for grupo_data in grupos:
        grupo = Group.objects.create(
            id=grupo_data['id'],
            name=grupo_data['name']
        )
        grupos_criados[grupo.id] = grupo
        print(f"   OK Grupo criado: {grupo.name} (ID: {grupo.id})")
    
    # Restaurar relacionamentos
    print("\n   Restaurando relacionamentos usuario-grupos:")
    total_relacoes = 0
    for relacao in relacoes:
        try:
            usuario = Usuario.objects.get(id=relacao['usuario_id'])
            grupo = grupos_criados.get(relacao['group_id'])
            if grupo:
                usuario.groups.add(grupo)
                total_relacoes += 1
                if total_relacoes <= 10:  # Mostrar apenas os primeiros 10
                    print(f"   OK Usuario ID {usuario.id} ({usuario.email}) -> Grupo {grupo.name}")
        except Usuario.DoesNotExist:
            print(f"   Aviso: Usuario ID {relacao['usuario_id']} nao encontrado")
            continue
    
    if total_relacoes > 10:
        print(f"   ... e mais {total_relacoes - 10} relacionamentos")
    
    # Verificar usuario Roger
    print("\n" + "=" * 80)
    print("VERIFICACAO - Usuario Roger:")
    usuario_roger = Usuario.objects.get(email='roggerio@gmail.com')
    print(f"Email: {usuario_roger.email}")
    print(f"Grupos:")
    for g in usuario_roger.groups.all():
        print(f"  - {g.name}")
    
    print("\n" + "=" * 80)
    print("OK SINCRONIZACAO CONCLUIDA!")
    print(f"   Total de grupos: {len(grupos_criados)}")
    print(f"   Total de relacionamentos: {total_relacoes}")
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
except Exception as e:
    print(f"ERRO: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
