"""
Script para atualizar número de contrato definitivo nos ContratoM10
a partir dos dados do FPD (ID_CONTRATO)
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, ContratoM10

print("\n" + "=" * 80)
print("🔗 ATUALIZAÇÃO DE NÚMEROS DE CONTRATO M10 COM BASE NO FPD")
print("=" * 80)

# Buscar todos os FPD que têm vínculo com M10
fpd_com_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=False).select_related('contrato_m10')

print(f"\n📊 Encontrados: {fpd_com_vinculo.count()} registros FPD com vínculo M10")

if fpd_com_vinculo.count() == 0:
    print("❌ Nenhum registro encontrado. Execute o matching primeiro!")
    exit()

# Contadores
atualizados = 0
ja_preenchidos = 0
vazios_fpd = 0

print("\n🔄 Processando...")

for fpd in fpd_com_vinculo:
    contrato_m10 = fpd.contrato_m10
    id_contrato_fpd = fpd.id_contrato.strip() if fpd.id_contrato else ''
    
    # Se o ID_CONTRATO do FPD estiver vazio, pular
    if not id_contrato_fpd:
        vazios_fpd += 1
        continue
    
    # Se o ContratoM10 já tem número de contrato definitivo, verificar se é diferente
    if contrato_m10.numero_contrato_definitivo:
        # Se for igual, não precisa atualizar
        if contrato_m10.numero_contrato_definitivo == id_contrato_fpd:
            ja_preenchidos += 1
            continue
    
    # Atualizar
    contrato_m10.numero_contrato_definitivo = id_contrato_fpd
    contrato_m10.save(update_fields=['numero_contrato_definitivo'])
    atualizados += 1
    
    if atualizados <= 5:
        print(f"   ✅ O.S {contrato_m10.ordem_servico}: Contrato Definitivo = {id_contrato_fpd}")

print("\n" + "=" * 80)
print("✅ PROCESSAMENTO CONCLUÍDO")
print("=" * 80)
print(f"📊 ESTATÍSTICAS:")
print(f"   Total com vínculo M10: {fpd_com_vinculo.count()}")
print(f"   Atualizados: {atualizados}")
print(f"   Já preenchidos (não alterados): {ja_preenchidos}")
print(f"   ID_CONTRATO vazio no FPD: {vazios_fpd}")

# Verificar resultado
contratos_com_definitivo = ContratoM10.objects.filter(numero_contrato_definitivo__isnull=False).exclude(numero_contrato_definitivo='')
print(f"\n🔍 VERIFICAÇÃO FINAL:")
print(f"   ContratoM10 com Nº Contrato Definitivo: {contratos_com_definitivo.count()}")

print("\n" + "=" * 80)
print("🎉 CONCLUÍDO!")
print("=" * 80)

input("\nPressione ENTER para fechar...")
