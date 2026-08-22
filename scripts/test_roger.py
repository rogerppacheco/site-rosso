#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from usuarios.models import Usuario

print("=== Verificando usuário Roger ===")
try:
    user = Usuario.objects.get(username='Roger')
    print(f'✓ User encontrado: {user.username}')
    print(f'  Is active: {user.is_active}')
    print(f'  Email: {user.email}')
    print(f'  First name: {user.first_name}')
    print(f'  Last name: {user.last_name}')
    
    # Verificar se tem senha configurada
    print(f'  Password hash: {user.password[:50]}...')
    
    # Testar algumas senhas comuns
    print("\n=== Testando senhas ===")
    for senha in ['roger', 'Roger', 'roger123', 'Roger123', '123456', 'admin123']:
        resultado = user.check_password(senha)
        print(f'  {senha}: {"✓ CORRETA" if resultado else "✗ errada"}')
        if resultado:
            break
    
except Usuario.DoesNotExist:
    print('✗ User Roger não encontrado')
    print('\n=== Listando usuários existentes ===')
    usuarios = Usuario.objects.all()[:10]
    for u in usuarios:
        print(f'  - {u.username} ({u.first_name} {u.last_name}) - ativo: {u.is_active}')
