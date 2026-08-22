#!/usr/bin/env python
"""
Script para preencher numero_contrato_definitivo baseado no FPD mesmo sem O.S exata
Usa o campo 'id_contrato' que foi preenchido na ImportacaoFPD
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD

print("=" * 80)
print("SOLUÇÃO: Preencher numero_contrato_definitivo com dados do FPD")
print("=" * 80)

# Estratégia: Usar importacoes FPD que têm id_contrato
# Mesmo que não encontrem O.S correspondente, podemos preencher manualmente

total_atualizados = 0
total_processados = 0

# Verificar quantos contratos já têm dados FPD associados
print("\n📊 Situação atual:")
print(f"   - Total ContratoM10: {ContratoM10.objects.count()}")
print(f"   - Total ImportacaoFPD: {ImportacaoFPD.objects.count()}")

# Para cada ImportacaoFPD que tem id_contrato, tentar associar
fpds_com_id = ImportacaoFPD.objects.filter(id_contrato__isnull=False).exclude(id_contrato='').values('id_contrato').distinct()
print(f"   - ImportacaoFPD com id_contrato válido: {fpds_com_id.count()}")

# Se FPD não encontrou contrato M10 na importação, pode ser porque:
# 1. A O.S é diferente (já verificamos - nenhuma em comum)
# 2. O contrato não foi criado ainda

# Solução: Buscar FPD que TENHA vínculo (criada com sucesso)
fpds_vinculadas = ImportacaoFPD.objects.filter(contrato_m10__isnull=False)
print(f"   - ImportacaoFPD vinculadas a ContratoM10: {fpds_vinculadas.count()}")

if fpds_vinculadas.count() > 0:
    print("\n✅ Encontradas FPDs vinculadas! Atualizando numero_contrato_definitivo...")
    
    for fpd in fpds_vinculadas:
        contrato = fpd.contrato_m10
        if fpd.id_contrato and not contrato.numero_contrato_definitivo:
            contrato.numero_contrato_definitivo = fpd.id_contrato
            contrato.save(update_fields=['numero_contrato_definitivo'])
            total_atualizados += 1
            total_processados += 1
        else:
            total_processados += 1
    
    print(f"   ✅ {total_atualizados} contratos atualizados com numero_contrato_definitivo")
else:
    print("\n❌ Nenhuma ImportacaoFPD vinculada ao ContratoM10!")
    print("\n💡 Próximos passos:")
    print("   1. Verifique se as O.S do arquivo FPD correspondem à base de ContratoM10")
    print("   2. Se forem bases diferentes, você pode:")
    print("      a. Reimportar o arquivo FPD com as O.S corretas, OU")
    print("      b. Fazer um manual matching entre FPD e ContratoM10")
    
    # Mostrar distribuição de O.S
    print("\n📋 Distribuição de O.S:")
    
    # Faixa de O.S nos Contratos
    contratos = list(ContratoM10.objects.values_list('ordem_servico', flat=True).distinct()[:10])
    fpds = list(ImportacaoFPD.objects.values_list('nr_ordem', flat=True).distinct()[:10])
    
    if contratos:
        min_c = min(contratos)
        max_c = max(contratos)
        print(f"   Contratos M10: {min_c} até {max_c}")
    
    if fpds:
        min_f = min(fpds)
        max_f = max(fpds)
        print(f"   FPD: {min_f} até {max_f}")
    
    # Verificar se há overlap de faixas
    if contratos and fpds:
        if (min_c <= min_f <= max_c) or (min_f <= min_c <= max_f):
            print("\n   ⚠️  Há overlap de faixas - pode haver correspondência parcial")
        else:
            print("\n   ❌ Faixas completamente diferentes - nenhuma correspondência esperada")

print("\n" + "=" * 80)
