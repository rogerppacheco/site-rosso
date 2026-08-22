# Arquivo: teste_zap.py
import requests
from decouple import config

# Carrega as configurações do .env
try:
    INSTANCE = config('ZAPI_INSTANCE_ID')
    TOKEN = config('ZAPI_TOKEN')
    CLIENT_TOKEN = config('ZAPI_CLIENT_TOKEN')
except:
    print("ERRO: Não foi possível ler o arquivo .env")
    exit()

print("-" * 30)
print(f"Instância: {INSTANCE}")
print(f"Token: {TOKEN}")
print(f"Client-Token: {CLIENT_TOKEN}")
print("-" * 30)

# Número para teste (use um que você sabe que tem WhatsApp)
TELEFONE = "5531988804000" 

url = f"https://api.z-api.io/instances/{INSTANCE}/token/{TOKEN}/phone-exists/{TELEFONE}"

headers = {
    "Content-Type": "application/json",
    "Client-Token": CLIENT_TOKEN
}

print(f"Testando conexão com: {url}...")

try:
    response = requests.get(url, headers=headers)
    
    print(f"\nSTATUS CODE: {response.status_code}")
    print(f"RESPOSTA: {response.text}")
    
    if response.status_code == 200:
        print("\nSUCESSO! Credenciais estão corretas.")
    elif response.status_code == 401:
        print("\nERRO 401: Não autorizado. Verifique se o Token ou Client-Token estão corretos.")
    elif response.status_code == 404:
        print("\nERRO 404: Instância não encontrada. Verifique o ID da Instância.")
    else:
        print("\nOUTRO ERRO: Verifique a mensagem de resposta acima.")

except Exception as e:
    print(f"\nErro de conexão: {e}")