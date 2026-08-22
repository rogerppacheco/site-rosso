"""
Teste de conexão com a Z-API (variáveis de ambiente).
Uso (a partir da raiz do projeto, com .env carregado): python scripts/debug/teste_conexao.py
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

import requests

instance_id = os.environ.get("ZAPI_INSTANCE_ID")
token = os.environ.get("ZAPI_TOKEN")
client_token = os.environ.get("ZAPI_CLIENT_TOKEN")

print("-" * 30)
print(f"Testando Instancia: {instance_id}")
print(f"Usando Token: {token}")
print("-" * 30)

if not instance_id or not token:
    print("ERRO CRITICO: As variaveis de ambiente nao foram carregadas!")
    sys.exit(1)

url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/status"
headers = {"client-token": client_token} if client_token else {}

print(f"Consultando URL: {url}")

try:
    response = requests.get(url, headers=headers, timeout=15)
    print(f"Status code: {response.status_code}")
    print(f"Resposta Z-API: {response.text}")
except Exception as e:
    print(f"Erro ao conectar: {e}")
    sys.exit(1)
