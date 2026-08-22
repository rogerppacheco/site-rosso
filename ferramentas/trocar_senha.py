#!/usr/bin/env python
"""
Script para trocar a senha de um usuário local
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from usuarios.models import Usuario

print("=" * 60)
print("TROCAR SENHA DE USUARIO")
print("=" * 60)

# Solicitar email do usuário
email = input("\nEmail do usuario (ex: roggerio@gmail.com): ").strip()

try:
    usuario = Usuario.objects.get(email=email)
    print(f"\nUsuario encontrado: {usuario.email}")
    print(f"Username: {usuario.username}")
    
    # Solicitar nova senha
    print("\n" + "-" * 60)
    senha_nova = input("Digite a NOVA senha: ").strip()
    
    if len(senha_nova) < 6:
        print("ERRO: A senha deve ter pelo menos 6 caracteres")
        sys.exit(1)
    
    senha_confirmacao = input("Confirme a nova senha: ").strip()
    
    if senha_nova != senha_confirmacao:
        print("ERRO: As senhas nao conferem!")
        sys.exit(1)
    
    # Trocar a senha
    usuario.set_password(senha_nova)
    usuario.save()
    
    print("\n" + "=" * 60)
    print("OK! Senha alterada com sucesso!")
    print("=" * 60)
    print(f"\nAgora voce pode fazer login com:")
    print(f"  Email: {usuario.email}")
    print(f"  Senha: (a que acabou de definir)")
    
except Usuario.DoesNotExist:
    print(f"ERRO: Usuario com email '{email}' nao encontrado!")
    print("\nUsuarios disponiveis:")
    usuarios = Usuario.objects.all().values_list('email', flat=True)
    for u in usuarios:
        print(f"  - {u}")
    sys.exit(1)
except Exception as e:
    print(f"ERRO: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
