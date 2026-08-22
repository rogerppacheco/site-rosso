#!/usr/bin/env python
"""
Script que marca como inativo os registros RecordApoia com nome_original
contendo 'pagina_9.jpg'. Execução direta, sem confirmação.

Recomendado: usar o comando Django (equivalente):
    python manage.py excluir_pagina_9 --remover

Uso (a partir da raiz do projeto):
    python scripts/excluir_pagina_9_rapido.py
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

import django
django.setup()

from crm_app.models import RecordApoia

arquivos = RecordApoia.objects.filter(nome_original__icontains="pagina_9.jpg")
print(f"Encontrados {arquivos.count()} arquivo(s):")
for arq in arquivos:
    print(f"  ID: {arq.id}, Titulo: {arq.titulo}, Nome: {arq.nome_original}")

if arquivos.exists():
    for arq in arquivos:
        arq.ativo = False
        arq.save()
        print(f"Arquivo ID {arq.id} marcado como inativo")
    print(f"✅ {arquivos.count()} arquivo(s) marcado(s) como inativo.")
else:
    print("Nenhum arquivo encontrado.")
