"""Avalia vendas 9098 e 9003 (CRM 500MB vs OSAB 1GB)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")
if os.environ.get("DATABASE_UNPOOLED_URL"):
    os.environ["DATABASE_URL"] = os.environ["DATABASE_UNPOOLED_URL"]
django.setup()

from crm_app.models import ImportacaoOsab, Venda

IDS = [9098, 9003]

for v in Venda.objects.filter(id__in=IDS).select_related("plano", "status_esteira", "cliente"):
    print("=" * 60)
    print(f"VENDA #{v.id}")
    print(f"  OS: {v.ordem_servico}")
    print(f"  Cliente: {v.cliente.nome_razao_social if v.cliente else '-'}")
    print(f"  Plano CRM: {v.plano.nome if v.plano else '-'} (R$ {v.plano.valor if v.plano else '-'})")
    print(f"  Esteira: {v.status_esteira.nome if v.status_esteira else '-'}")
    print(f"  Data instalacao: {v.data_instalacao}")
    os_val = (v.ordem_servico or "").strip()
    osab = ImportacaoOsab.objects.filter(documento=os_val).first()
    if not osab:
        alts = list(ImportacaoOsab.objects.filter(documento__endswith=os_val[-7:])[:3])
        print(f"  OSAB: NAO ENCONTRADO (alts={[a.documento for a in alts]})")
        continue
    print(f"  OSAB velocidade: {osab.velocidade}")
    print(f"  OSAB oferta: {osab.oferta}")
    print(f"  OSAB produto: {osab.produto}")
    oferta = (osab.oferta or "").upper()
    tem_75 = "_75_" in oferta or oferta.endswith("_75") or "_75" in oferta.split("_")
    tem_mesh = "FIBRAX_MESH" in oferta or ("MESH" in oferta and "SEM MESH" not in oferta)
    if "1GB" in (osab.velocidade or "").upper() or "1000" in (osab.velocidade or ""):
        if tem_75 or not tem_mesh:
            sugerido = "NIO FIBRA ULTRA 1GB (SEM MESH)"
        else:
            sugerido = "NIO FIBRA ULTRA 1GB"
    else:
        sugerido = "?"
    print(f"  SUGERIDO: {sugerido}  (75={tem_75}, mesh={tem_mesh})")
