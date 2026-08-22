"""
Script para testar o webhook do WhatsApp localmente
"""
import requests
import json

# URL do webhook (ajuste conforme necessário)
WEBHOOK_URL = "http://127.0.0.1:8000/api/crm/webhook-whatsapp/"

# Teste 1: Formato Z-API padrão
payload1 = {
    "phone": "5511999999999",
    "message": {
        "text": "Fachada"
    }
}

# Teste 2: Formato alternativo
payload2 = {
    "from": "5511999999999",
    "body": "Fachada"
}

# Teste 3: Formato direto
payload3 = {
    "phone": "5511999999999",
    "text": "Fachada"
}

print("=" * 60)
print("TESTE DO WEBHOOK WHATSAPP")
print("=" * 60)

for i, payload in enumerate([payload1, payload2, payload3], 1):
    print(f"\n--- Teste {i} ---")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"Status: {response.status_code}")
        print(f"Resposta: {response.text}")
        if response.status_code == 200:
            print("OK - SUCESSO!")
        else:
            print("ERRO!")
    except Exception as e:
        print(f"ERRO na requisicao: {e}")

print("\n" + "=" * 60)
print("Testes concluídos!")
print("=" * 60)
