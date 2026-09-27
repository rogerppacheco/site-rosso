import requests
import pandas as pd
import re

# Faz login
url_login = 'https://site-gm-production.up.railway.app/api/auth/login/'
data = {'username': 'admin', 'password': 'X4RkZSPAuoJL6jWU'}
res_login = requests.post(url_login, json=data)
if res_login.status_code != 200:
    print(f"Falha no login: {res_login.status_code} {res_login.text}")
    exit(1)

token = res_login.json().get('token')
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Carregar usuários
print("Carregando usuários...")
res_users = requests.get('https://site-gm-production.up.railway.app/api/usuarios/?limit=1000', headers=headers)
users = res_users.json().get('results', []) if res_users.status_code == 200 else []
users_map_exact = {u['nome_completo'].strip().lower(): u for u in users if u.get('nome_completo')}
users_map_first = {u['nome_completo'].split()[0].lower(): u for u in users if u.get('nome_completo')}

path = r'C:\Users\rogge\Downloads\Planilha Vendas_Clientes (2).xlsx'
df = pd.read_excel(path)

count_atualizados = 0
count_nao_encontrado_os = 0
count_nao_encontrado_vendedor = 0
count_mesmo_vendedor = 0

for index, row in df.iterrows():
    os_num_raw = str(row.get('OS', '')).strip()
    os_num = re.sub(r'\D', '', os_num_raw)
    vendedor_nome = str(row.get('VENDEDOR', '')).strip()
    
    if not os_num or os_num == 'nan' or not vendedor_nome or vendedor_nome == 'nan':
        continue
        
    os_num_trim = os_num[:-1] if os_num.endswith('0') else os_num

    # Buscar OS usando ?search=
    res_venda = requests.get(f'https://site-gm-production.up.railway.app/api/crm/vendas/?view=geral&search={os_num_trim}', headers=headers)
    if res_venda.status_code != 200 or not res_venda.json().get('results'):
        print(f"OS não encontrada: {os_num} nem {os_num_trim}")
        count_nao_encontrado_os += 1
        continue
    
    vendas_encontradas = res_venda.json().get('results', [])
    venda = None
    for v in vendas_encontradas:
        if os_num_trim in str(v.get('ordem_servico', '')):
            venda = v
            break

    if not venda:
        print(f"OS não encontrada (falso positivo na busca): {os_num}")
        count_nao_encontrado_os += 1
        continue
        
    venda_id = venda['id']
    vendedor_atual_id = venda.get('vendedor')
    
    # Encontrar Usuário
    u_target = users_map_exact.get(vendedor_nome.lower())
    if not u_target:
        primeiro_nome = vendedor_nome.split()[0].lower()
        u_target = users_map_first.get(primeiro_nome)
        
    if u_target:
        if str(vendedor_atual_id) != str(u_target['id']):
            res_patch = requests.patch(f'https://site-gm-production.up.railway.app/api/crm/vendas/{venda_id}/', headers=headers, json={'vendedor': u_target['id']})
            if res_patch.status_code in [200, 204]:
                print(f"Atualizando OS {os_num}: -> {u_target['nome_completo']}")
                count_atualizados += 1
            else:
                print(f"Falha ao atualizar OS {os_num}: {res_patch.text}")
        else:
            count_mesmo_vendedor += 1
    else:
        print(f"Vendedor não encontrado no CRM: '{vendedor_nome}' (OS: {os_num})")
        count_nao_encontrado_vendedor += 1

print(f"\nResumo:")
print(f"Atualizados: {count_atualizados}")
print(f"Já com o mesmo vendedor: {count_mesmo_vendedor}")
print(f"OS não encontrada no CRM: {count_nao_encontrado_os}")
print(f"Vendedor não encontrado no CRM: {count_nao_encontrado_vendedor}")
