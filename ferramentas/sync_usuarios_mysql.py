#!/usr/bin/env python
"""
Script simples para sincronizar usuários do banco em produção.
"""
import os
import sys
from urllib.parse import urlparse

# URL do banco em produção
DB_URL = "mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45"

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

print("=" * 80)
print("SINCRONIZACAO DE USUARIOS - PRODUCAO -> LOCAL")
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
    
    print(f"\nOK Conectado ao banco em produção!")
    print(f"   Host: {parsed.hostname}")
    print(f"   Database: {parsed.path.lstrip('/')}")
    
    # Buscar usuários
    print("\n[1/3] Buscando usuarios em producao...")
    
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM usuarios_usuario")
    usuarios = cursor.fetchall()
    
    print(f"OK Encontrados {len(usuarios)} usuario(s)")
    
    cursor.close()
    connection.close()
    
    # Deletar usuários antigos e restaurar novos
    print("\n[2/3] Restaurando no banco local...")
    
    from usuarios.models import Usuario
    
    # Limpar banco local
    Usuario.objects.all().delete()
    print("   - Usuários antigos removidos")
    
    # Inserir novos
    total_criados = 0
    for i, user_data in enumerate(usuarios):
        try:
            # Garantir que username é unique
            username = user_data.get('username')
            if not username:
                # Usar email como base para username
                username = user_data['email'].split('@')[0]
                # Se duplicado, adicionar número
                if Usuario.objects.filter(username=username).exists():
                    username = f"{username}{i}"
            
            usuario = Usuario(
                id=user_data['id'],
                email=user_data['email'],
                username=username,
                password=user_data['password'],
                is_staff=bool(user_data['is_staff']),
                is_superuser=bool(user_data['is_superuser']),
                is_active=bool(user_data['is_active']),
                first_name=user_data.get('first_name') or '',
                last_name=user_data.get('last_name') or '',
                date_joined=user_data['date_joined'],
                last_login=user_data.get('last_login'),
            )
            usuario.save()
            total_criados += 1
            
            # Mostrar alguns usuarios
            if i < 5 or i % 10 == 0:
                print(f"   OK {usuario.email} (ID: {usuario.id})")
        except Exception as e:
            print(f"   ERRO ao criar ID {user_data['id']}: {str(e)}")
            continue
    
    total_local = Usuario.objects.count()
    print(f"\nOK SINCRONIZACAO CONCLUIDA!")
    print(f"   Usuarios criados: {total_criados}")
    print(f"   Total no banco local: {total_local}")
    
    # Mostrar primeiro usuário como teste
    primeiro = Usuario.objects.first()
    if primeiro:
        print(f"\n   Exemplo - Primeiro usuario:")
        print(f"   Email: {primeiro.email}")
        print(f"   Username: {primeiro.username}")
        print(f"   Ativo: {primeiro.is_active}")
    
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

print("\n" + "=" * 80)
