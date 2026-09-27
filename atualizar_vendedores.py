import pandas as pd
from crm_app.models import Venda
from usuarios.models import Usuario
import re

path = r'C:\Users\rogge\Downloads\Planilha Vendas_Clientes (2).xlsx'
df = pd.read_excel(path)

count_atualizados = 0
count_nao_encontrado_os = 0
count_nao_encontrado_vendedor = 0

for index, row in df.iterrows():
    os_num = str(row.get('OS', '')).strip()
    # Remove tudo que não for dígito da OS
    os_num = re.sub(r'\D', '', os_num)
    vendedor_nome = str(row.get('VENDEDOR', '')).strip()
    
    if not os_num or os_num == 'nan' or not vendedor_nome or vendedor_nome == 'nan':
        continue

    vendas = Venda.objects.filter(ordem_servico=os_num)
    if not vendas.exists():
        count_nao_encontrado_os += 1
        continue
        
    for venda in vendas:
        # Tentar match exato
        usuario = Usuario.objects.filter(nome__iexact=vendedor_nome).first()
        if not usuario:
            # Tentar pelo primeiro nome
            primeiro_nome = vendedor_nome.split()[0]
            usuario = Usuario.objects.filter(nome__icontains=primeiro_nome).first()
            
        if usuario:
            if venda.vendedor != usuario:
                print(f"Atualizando OS {os_num}: {getattr(venda.vendedor, 'nome', 'Nenhum')} -> {usuario.nome}")
                venda.vendedor = usuario
                venda.save()
                count_atualizados += 1
        else:
            print(f"Vendedor não encontrado no CRM: '{vendedor_nome}' (OS: {os_num})")
            count_nao_encontrado_vendedor += 1

print(f"\nResumo:")
print(f"Atualizados: {count_atualizados}")
print(f"OS não encontrada no CRM: {count_nao_encontrado_os}")
print(f"Vendedor não encontrado no CRM: {count_nao_encontrado_vendedor}")
