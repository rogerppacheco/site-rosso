#!/usr/bin/env python
"""
Atualizar status das faturas com base no novo mapeamento de FPD
"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, FaturaM10
from fpd_status_mapping import normalizar_status_fpd

# Lista de O.S que precisam ser atualizadas
os_list = [
    '07613763', '07586057', '07657651', '07589136', '07605574', '07713128', '07826707', '07681609',
    '07533496', '07713770', '07743876', '07861018', '07566502', '07788920', '07536110', '07659939',
    '07864318', '07557881', '07561624', '07600659', '07689712', '07581780', '07713908', '07715539',
    '07599413', '07703123', '07629533', '07840955', '07579956', '07660818', '07642770', '07739828',
    '07588330', '07741723', '07521996', '07635817', '07631553', '07714540', '07738664', '07536043',
    '07807366', '07565688', '07713860', '07657195', '07632373', '07666515', '07771151', '07865594',
    '07529021', '07727880', '07690031', '07764158', '07581954', '07678561', '07627848', '07531525',
    '07679845', '07657141', '07761984', '07626476', '07776615', '07745454', '07714344', '07701586',
    '07568304', '07605343', '07582955', '07827793', '07585734', '07714325', '07740001', '07599645',
    '07694487', '07568000', '07406463', '07802902', '07746085', '07772293', '07815165', '07803991',
    '07597411', '07590326',
]

print(f"Total de O.S para verificar/atualizar: {len(os_list)}")

# Buscar contratos
contratos = ContratoM10.objects.filter(ordem_servico__in=os_list)
print(f"Contratos encontrados: {contratos.count()}")

atualizadas = 0
nao_encontradas = 0
ja_corretas = 0

for os in os_list:
    try:
        contrato = ContratoM10.objects.get(ordem_servico=os)
        
        # Verificar status FPD do contrato
        status_fpd_raw = contrato.status_fatura_fpd
        if not status_fpd_raw:
            print(f"⚠ O.S {os}: status_fatura_fpd está vazio")
            continue
        
        # Normalizar status de acordo com o novo mapeamento
        status_esperado = normalizar_status_fpd(status_fpd_raw)
        
        # Atualizar TODAS as faturas do contrato (não só a fatura 1)
        faturas = FaturaM10.objects.filter(contrato=contrato)
        
        if not faturas.exists():
            print(f"⚠ O.S {os}: Nenhuma fatura encontrada")
            continue
        
        faturas_atualizadas = 0
        for fatura in faturas:
            if fatura.status != status_esperado:
                fatura.status = status_esperado
                fatura.save()
                faturas_atualizadas += 1
        
        if faturas_atualizadas > 0:
            print(f"↻ O.S {os}: {faturas_atualizadas} faturas atualizadas para '{status_esperado}' (FPD: {status_fpd_raw})")
            atualizadas += 1
        else:
            ja_corretas += 1
    
    except ContratoM10.DoesNotExist:
        nao_encontradas += 1
        print(f"✗ O.S {os}: Contrato não encontrado")

print(f"\n{'='*60}")
print(f"RESUMO:")
print(f"  ✓ Já corretas: {ja_corretas}")
print(f"  ↻ Atualizadas: {atualizadas}")
print(f"  ✗ Não encontradas: {nao_encontradas}")
print(f"{'='*60}")

# Verificação final: contar faturas PAGO na safra 2025-12
print(f"\nVerificação final:")
faturas_pago = FaturaM10.objects.filter(
    contrato__safra='2025-12',
    numero_fatura=1,
    status='PAGO'
).count()
print(f"Faturas com status PAGO na safra 2025-12: {faturas_pago}")
