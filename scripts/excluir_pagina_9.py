#!/usr/bin/env python
"""
Script para excluir o arquivo pagina_9.jpg do RecordApoia
"""
import os
import sys
import django

# Configurar Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'site_record.settings')
django.setup()

from crm_app.models import RecordApoia

def excluir_pagina_9():
    """Exclui arquivos com nome_original contendo 'pagina_9.jpg'"""
    arquivos = RecordApoia.objects.filter(nome_original__icontains='pagina_9.jpg')
    
    if not arquivos.exists():
        print("❌ Nenhum arquivo 'pagina_9.jpg' encontrado.")
        return
    
    print(f"🔍 Encontrados {arquivos.count()} arquivo(s):")
    for arq in arquivos:
        print(f"  - ID: {arq.id}")
        print(f"    Título: {arq.titulo}")
        print(f"    Nome Original: {arq.nome_original}")
        print(f"    Tipo: {arq.tipo_arquivo}")
        print(f"    Ativo: {arq.ativo}")
        print()
    
    confirmacao = input(f"Deseja excluir {arquivos.count()} arquivo(s)? (digite 'SIM' para confirmar): ").strip().upper()
    
    if confirmacao != 'SIM':
        print("❌ Operação cancelada.")
        return
    
    # Soft delete (marcar como inativo)
    for arq in arquivos:
        arq.ativo = False
        arq.save()
        print(f"✅ Arquivo ID {arq.id} ({arq.titulo}) marcado como inativo.")
    
    print(f"\n✅ {arquivos.count()} arquivo(s) excluído(s) com sucesso!")

if __name__ == "__main__":
    print("=" * 60)
    print("SCRIPT DE EXCLUSÃO - pagina_9.jpg")
    print("=" * 60)
    print()
    excluir_pagina_9()
