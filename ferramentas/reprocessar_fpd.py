#!/usr/bin/env python
"""
Script para reprocessar ImportacaoFPD existentes e vinculá-los aos ContratoM10 agora que foram criados
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from crm_app.models import ContratoM10, ImportacaoFPD

print("=" * 80)
print("REPROCESSAMENTO: Vinculando ImportacaoFPD aos ContratoM10 existentes")
print("=" * 80)

# Encontrar ImportacaoFPD sem contrato_m10
fpds_sem_contrato = ImportacaoFPD.objects.filter(contrato_m10__isnull=True)
print(f"\n📊 Total de ImportacaoFPD sem vínculo: {fpds_sem_contrato.count()}")

# Tentar vinculá-los
vinculados = 0
nao_encontrados = 0
erros = 0

for fpd in fpds_sem_contrato:
    try:
        # Buscar contrato pela O.S (nr_ordem)
        try:
            contrato = ContratoM10.objects.get(ordem_servico=fpd.nr_ordem)
            fpd.contrato_m10 = contrato
            fpd.save()
            vinculados += 1
            
            # Atualizar o numero_contrato_definitivo do contrato se o FPD tem id_contrato
            if fpd.id_contrato and not contrato.numero_contrato_definitivo:
                contrato.numero_contrato_definitivo = fpd.id_contrato
                contrato.save(update_fields=['numero_contrato_definitivo'])
            
            if vinculados <= 10:
                print(f"   ✅ FPD O.S {fpd.nr_ordem} vinculada ao Contrato")
                
        except ContratoM10.DoesNotExist:
            nao_encontrados += 1
            if nao_encontrados <= 5:
                print(f"   ❌ FPD O.S {fpd.nr_ordem} - Contrato não encontrado")
                
    except Exception as e:
        erros += 1
        if erros <= 3:
            print(f"   ⚠️  Erro ao processar FPD O.S {fpd.nr_ordem}: {str(e)[:50]}")

print(f"\n📊 Resultados:")
print(f"   ✅ Vinculadas: {vinculados}")
print(f"   ❌ Não encontradas: {nao_encontrados}")
print(f"   ⚠️  Erros: {erros}")

# Verificar resultado final
contratos_com_numero_def = ContratoM10.objects.filter(numero_contrato_definitivo__isnull=False).exclude(numero_contrato_definitivo='').count()
print(f"\n🎯 Contratos com numero_contrato_definitivo agora: {contratos_com_numero_def}")

print("\n" + "=" * 80)
