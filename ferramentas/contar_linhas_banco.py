"""
Script para contar total de linhas nas principais tabelas
"""
from django.db import connection

cursor = connection.cursor()

print("\\n" + "="*60)
print("PRINCIPAIS TABELAS - CONTAGEM DE LINHAS")
print("="*60)

tabelas = [
    ('crm_app_venda', 'Vendas'),
    ('crm_app_contratom10', 'Contratos M-10'),
    ('crm_app_faturam10', 'Faturas M-10'),
    ('crm_app_safram10', 'Safras M-10'),
    ('crm_app_importacaofpd', 'ImportacaoFPD'),
    ('crm_app_importacaochurn', 'ImportacaoChurn'),
    ('crm_app_logimportacaofpd', 'Logs FPD'),
    ('crm_app_logimportacaochurn', 'Logs Churn'),
    ('crm_app_cliente', 'Clientes'),
    ('crm_app_vendedor', 'Vendedores'),
    ('auth_user', 'Usuários'),
]

total = 0
for table_name, label in tabelas:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        count = cursor.fetchone()[0]
        print(f"{label:30} {count:>10,} linhas")
        total += count
    except Exception as e:
        print(f"{label:30} Erro: {e}")

print("-"*60)
print(f"{'TOTAL (principais):':30} {total:>10,} linhas")
print("="*60)

# Análise
pct = (total/10000)*100
print(f"\\n📊 USO DO LIMITE 10K: {pct:.1f}%")

if total < 5000:
    print("✅ Muito confortável para Postgres Hobby Dev (GRATUITO)")
elif total < 8000:
    print("✅ Confortável para Postgres Hobby Dev (GRATUITO)")
else:
    print("⚠️  Considere Standard-0 ($50/mês)")
