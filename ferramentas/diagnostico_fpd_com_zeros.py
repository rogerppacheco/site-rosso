"""
Verificar status da importação FPD com zeros
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, LogImportacaoFPD

print("\n" + "=" * 100)
print("🔍 DIAGNÓSTICO DE IMPORTAÇÃO FPD")
print("=" * 100)

# Verificar ImportacaoFPD
print("\n1️⃣ Tabela ImportacaoFPD:")
total_fpd = ImportacaoFPD.objects.count()
print(f"   Total de registros: {total_fpd}")

if total_fpd > 0:
    print(f"\n   Amostra de 10 registros:")
    for imp in ImportacaoFPD.objects.all()[:10]:
        print(f"   - O.S: {imp.nr_ordem} (len: {len(imp.nr_ordem)}), Fatura: {imp.nr_fatura}, Valor: R$ {imp.vl_fatura}")
    
    # Verificar se tem zeros
    print(f"\n   Verificando formato de O.S:")
    primeira = ImportacaoFPD.objects.first()
    print(f"   Primeira O.S: '{primeira.nr_ordem}'")
    print(f"   Começa com zero? {primeira.nr_ordem.startswith('0')}")
    print(f"   Tem 8 dígitos? {len(primeira.nr_ordem) == 8}")

# Verificar LogImportacaoFPD
print("\n2️⃣ Tabela LogImportacaoFPD:")
total_logs = LogImportacaoFPD.objects.count()
print(f"   Total de logs: {total_logs}")

if total_logs > 0:
    ultimo_log = LogImportacaoFPD.objects.order_by('-iniciado_em').first()
    print(f"\n   Último log:")
    print(f"   - Status: {ultimo_log.status}")
    print(f"   - Total linhas: {ultimo_log.total_linhas}")
    print(f"   - Processadas: {ultimo_log.total_processadas}")
    print(f"   - Criadas: {ultimo_log.total_processadas}")
    print(f"   - Com M10: {ultimo_log.total_linhas - ultimo_log.total_contratos_nao_encontrados}")
    print(f"   - Sem M10: {ultimo_log.total_contratos_nao_encontrados}")
    if ultimo_log.mensagem_erro:
        print(f"   - Erro: {ultimo_log.mensagem_erro[:100]}")

# Buscar as O.S que o usuário mencionou
print("\n3️⃣ Buscando O.S específicas do usuário:")
oses_usuario = [
    '07309961', '07276824', '06617961', '07613763', '07281192',
    '07586057', '07155718', '06924199', '06696745', '07808998',
    '06513261', '07690685'
]

encontradas = 0
para_exemplo = []

for os in oses_usuario:
    registro = ImportacaoFPD.objects.filter(nr_ordem=os).first()
    if registro:
        encontradas += 1
        if len(para_exemplo) < 3:
            para_exemplo.append(f"{registro.nr_ordem} - Fatura: {registro.nr_fatura}")
    else:
        print(f"   ❌ {os} - NÃO ENCONTRADA")

print(f"\n   ✅ Encontradas: {encontradas}/{len(oses_usuario)}")
if para_exemplo:
    print(f"   Exemplos: {para_exemplo}")

print("\n" + "=" * 100)
