"""
Script para encontrar e remover arquivo PANFLETO_NIO.pdf do Record Apoia.
Use com cuidado - remove definitivamente do banco de dados.
"""
import os
import sys
from pathlib import Path
import django

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
django.setup()

from crm_app.models import RecordApoia
from django.db.models import Q

def buscar_panfleto():
    """Busca arquivos com PANFLETO no título ou nome"""
    print("🔍 Buscando arquivos com 'PANFLETO' no título ou nome...")
    
    arquivos = RecordApoia.objects.filter(
        Q(titulo__icontains='PANFLETO') | Q(nome_original__icontains='PANFLETO')
    )
    
    if not arquivos.exists():
        print("✅ Nenhum arquivo encontrado com 'PANFLETO'")
        return []
    
    print(f"\n📋 Encontrados {arquivos.count()} arquivo(s):\n")
    resultados = []
    
    for arq in arquivos:
        print(f"ID: {arq.id}")
        print(f"Título: {arq.titulo}")
        print(f"Nome Original: {arq.nome_original}")
        print(f"Ativo: {arq.ativo}")
        print(f"Data Upload: {arq.data_upload}")
        print(f"Arquivo Path: {arq.arquivo.name if arq.arquivo else 'N/A'}")
        print("-" * 50)
        
        resultados.append({
            'id': arq.id,
            'titulo': arq.titulo,
            'nome_original': arq.nome_original,
            'ativo': arq.ativo
        })
    
    return resultados

def remover_panfleto(confirmar=True):
    """Remove arquivos PANFLETO do banco"""
    arquivos = buscar_panfleto()
    
    if not arquivos:
        return
    
    if confirmar:
        print("\n⚠️  ATENÇÃO: Esta operação irá REMOVER DEFINITIVAMENTE do banco de dados!")
        resposta = input(f"Deseja remover {len(arquivos)} arquivo(s)? (digite 'SIM' para confirmar): ").strip().upper()
        if resposta != 'SIM':
            print(f"❌ Operação cancelada. (Resposta recebida: '{resposta}')")
            return
    
    from django.db import transaction
    
    with transaction.atomic():
        for info in arquivos:
            try:
                arq = RecordApoia.objects.get(id=info['id'])
                titulo = arq.titulo
                arq.delete()  # Remove definitivamente
                print(f"✅ Removido: {titulo} (ID: {info['id']})")
            except RecordApoia.DoesNotExist:
                print(f"⚠️  Arquivo ID {info['id']} não encontrado (já foi removido?)")
            except Exception as e:
                print(f"❌ Erro ao remover ID {info['id']}: {e}")
    
    print(f"\n✅ Limpeza concluída! {len(arquivos)} arquivo(s) removido(s).")

if __name__ == "__main__":
    from django.db.models import Q
    
    print("=" * 60)
    print("SCRIPT DE LIMPEZA - PANFLETO_NIO.pdf")
    print("=" * 60)
    
    # Se passar --remover, remove direto (sem buscar duas vezes)
    if '--remover' in sys.argv:
        remover_panfleto(confirmar=True)
    else:
        # Primeiro, apenas buscar e mostrar
        arquivos = buscar_panfleto()
        
        if arquivos:
            print("\n" + "=" * 60)
            print("Para remover os arquivos, execute:")
            print("  railway run python scripts/limpar_panfleto_nio.py --remover")
            print("=" * 60)
        else:
            print("\n✅ Nenhum arquivo para remover.")
